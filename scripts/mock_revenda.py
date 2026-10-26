"""Mock da revenda de ingressos para demonstração (o servidor precisa das chaves da revenda no .env).

O que faz, chamando a própria API (nada é escrito direto no banco):
  1. cria 3 vendedores de teste (Marina Costa, Rafael Souza, Beatriz Nunes) e completa endereço, CPF e telefone deles
     e da conta de teste de fã;
  2. liga a revenda do show de São Paulo (esgotado na ticketeira + revenda aberta);
  3. cada vendedor cria 2 anúncios (Pista, Pista Premium e Camarote, todos abaixo do valor de face) e o admin aprova;
  4. a fã compra 3 ingressos para mostrar cada etapa: um pago (aguardando transferência), um já transferido
     (aguardando a confirmação dela) e um concluído e avaliado (a Beatriz passa a ter 1 venda e nota 5).
     O pagamento é simulado e exige RESALE_ALLOW_FAKE_PAYMENT=true.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_revenda.py

Pode rodar de novo: reaproveita contas e cria só anúncios e compras novos (cada vendedor aceita até 5 anúncios por hora).
Troque a senha das contas de teste (`CONTAS_SENHA`, mesma dos outros mocks) se o servidor for público.
Para testar fora do container: BASE=http://localhost:8001.
"""

import json
import os
import struct
import urllib.error
import urllib.request
import uuid
import zlib

BASE = os.environ.get("BASE", "http://localhost:8000")
SLUG = os.environ.get("ARTIST", "vintage-culture")
PASSWORD = os.environ.get("CONTAS_SENHA", "senha123")
SELLERS = [
    ("marina.revenda@teste.com", "Marina Costa", "@marina.c", "11988881234", [("Pista", 3, 14000), ("Camarote", 2, 34000)]),
    ("rafael.revenda@teste.com", "Rafael Souza", "@rafa.souza", "11977772345", [("Pista", 2, 14500), ("Pista Premium", 2, 22500)]),
    ("beatriz.revenda@teste.com", "Beatriz Nunes", "@bia.nunes", "11966663456", [("Pista Premium", 1, 23500), ("Pista", 4, 13000)]),
]
FAN = "juliacristinalopes2607@gmail.com"
ADMIN = "admin@vintage.com.br"
ADDR = {"zipCode": "01310-100", "street": "Av. Paulista", "number": "1000", "complement": "", "neighborhood": "Bela Vista", "city": "São Paulo", "state": "SP"}


def call(method, path, body=None, token=None, headers=None, raw=None):
    h = {"content-type": "application/json"} if body is not None else {}
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try:
            return e.code, json.loads(t)
        except ValueError:
            return e.code, t


def login(email):
    code, r = call("POST", "/auth/login", {"email": email, "password": PASSWORD})
    if code != 200:
        raise SystemExit(f"login de {email} falhou ({code}): {r}")
    return r["token"]


def png() -> bytes:
    """PNG pequeno e diferente a cada chamada (a API recusa a mesma prova em dois anúncios do mesmo show)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + os.urandom(8 * 3) for _ in range(8))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def multipart(fields, fbytes):
    b = uuid.uuid4().hex
    out = b""
    for k, vs in fields.items():
        for v in vs if isinstance(vs, list) else [vs]:
            out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += f'--{b}\r\nContent-Disposition: form-data; name="proof"; filename="ingresso.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + fbytes + f"\r\n--{b}--\r\n".encode()
    return out, b


def cpf(base: str) -> str:
    """CPF válido a partir de 9 dígitos (só para as contas de teste)."""
    d = [int(c) for c in base]
    for n in (9, 10):
        d.append((sum(v * (n + 1 - i) for i, v in enumerate(d)) * 10 % 11) % 10)
    return "".join(map(str, d))


def main():
    t_fan, t_admin = login(FAN), login(ADMIN)
    print("endereço da fã:", call("PUT", "/auth/address", ADDR, t_fan)[0])
    print("identidade da fã:", call("PUT", "/me/identity", {"cpf": cpf("111444777"), "phone": "11977774321"}, t_fan)[0])

    code, events = call("GET", f"/artists/{SLUG}/resale/admin/events", None, t_admin)
    if code != 200:
        raise SystemExit(f"admin da revenda: {code} {events}. Confira RESALE_PII_KEY e RESALE_PEPPER no .env.")
    ev = next((e for e in events if "Paulo" in e["city"]), None)
    if not ev:
        raise SystemExit("show de São Paulo não encontrado")
    code, r = call("PUT", f"/artists/{SLUG}/resale/admin/events/{ev['id']}", {"ticketingSoldOut": True, "resaleOpen": True}, t_admin)
    print("revenda de São Paulo aberta:", code, "isOpen =", r.get("isOpen") if isinstance(r, dict) else r)
    code, det = call("GET", f"/artists/{SLUG}/resale/events/{ev['id']}", None, t_fan)
    types = {t["label"]: t for t in det["ticketTypes"]}

    tokens, listings = {}, {}
    for n, (email, name, handle, phone, items) in enumerate(SELLERS):
        code, _ = call("POST", "/auth/register", {"name": name, "email": email, "password": PASSWORD, "handle": handle, "artist": SLUG, **ADDR})
        tokens[email] = tok = login(email)
        call("PUT", "/me/identity", {"cpf": cpf(f"52998224{n}"), "phone": phone}, tok)
        print(f"{name}: {'criada' if code == 201 else 'já existia'}")
        for label, qty, price in items:
            t = types[label]
            stamp = uuid.uuid4().hex[:6].upper()
            codes = [f"{name[:2].upper()}-{stamp}-{i + 1}" for i in range(qty)]
            body, b = multipart({"ticketId": t["id"], "qty": qty, "unitPriceCents": min(price, t["faceCents"]), "codes": codes}, png())
            code, r = call("POST", f"/artists/{SLUG}/resale/events/{ev['id']}/listings", token=tok, headers={"content-type": "multipart/form-data; boundary=" + b}, raw=body)
            print(f"  anúncio {label} x{qty}:", code, "" if code == 201 else r)
            if code == 201:
                call("POST", f"/artists/{SLUG}/resale/admin/listings/{r['id']}/approve", {}, t_admin)
                listings.setdefault((email, label), r)

    def buy(email, label, steps):
        li = listings.get((email, label))
        if not li:
            return print(f"  sem anúncio de {label} de {email}: compra pulada")
        code, o = call("POST", f"/artists/{SLUG}/resale/listings/{li['id']}/orders", {"qty": 1}, t_fan, headers={"Idempotency-Key": uuid.uuid4().hex})
        print(f"compra de {label}:", code, o.get("status") if isinstance(o, dict) else o)
        if code != 201:
            return
        base = f"/artists/{SLUG}/resale/orders/{o['id']}"
        who = {"pay": t_fan, "transferred": tokens[email], "confirm": t_fan}
        for step in steps:
            if step == "review":
                code, r = call("POST", base + "/review", {"rating": 5, "comment": "Tudo certo, transferência rápida."}, t_fan)
            else:
                code, r = call("POST", f"{base}/{step}", {}, who[step])
            print(f"  {step}:", code, r.get("status") if isinstance(r, dict) else r)
            if code != 200 and code != 201:
                if step == "pay":
                    print("  (para pagar de mentira, ponha RESALE_ALLOW_FAKE_PAYMENT=true no .env e reinicie a API)")
                return

    buy("marina.revenda@teste.com", "Pista", ["pay"])
    buy("rafael.revenda@teste.com", "Pista Premium", ["pay", "transferred"])
    buy("beatriz.revenda@teste.com", "Pista", ["pay", "transferred", "confirm", "review"])
    print("pronto. Abra /%s/revenda/%s logada como a fã de teste." % (SLUG, ev["id"]))


main()
