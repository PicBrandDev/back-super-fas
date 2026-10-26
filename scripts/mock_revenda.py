"""Mock da revenda de ingressos para demonstração (o servidor precisa das chaves da revenda no .env).

O que faz, chamando a própria API (nada é escrito direto no banco):
  1. cria a vendedora de teste "Marina Costa" e completa endereço/CPF/telefone dela e da conta de teste de fã;
  2. liga a revenda do show de São Paulo (esgotado na ticketeira + revenda aberta);
  3. a vendedora cria 2 anúncios (Pista e Pista Premium) e o admin aprova;
  4. a fã reserva e paga 1 ingresso de Pista (pagamento simulado, exige RESALE_ALLOW_FAKE_PAYMENT=true).

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_revenda.py

Pode rodar de novo: reaproveita o que já existe e só cria anúncios novos. Troque a senha das contas de teste
(`CONTAS_SENHA`, mesma dos outros mocks) se o servidor for público. Para testar fora do container: BASE=http://localhost:8001.
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
SELLER = ("marina.revenda@teste.com", "Marina Costa", "@marina.c")
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


def main():
    code, r = call("POST", "/auth/register", {"name": SELLER[1], "email": SELLER[0], "password": PASSWORD, "handle": SELLER[2], "artist": SLUG, **ADDR})
    print("vendedora:", "criada" if code == 201 else f"já existia ({code})")
    t_seller, t_fan, t_admin = login(SELLER[0]), login(FAN), login(ADMIN)

    print("endereço da fã:", call("PUT", "/auth/address", ADDR, t_fan)[0])
    print("identidade da vendedora:", call("PUT", "/me/identity", {"cpf": "529.982.247-25", "phone": "(11) 98888-1234"}, t_seller)[0])
    print("identidade da fã:", call("PUT", "/me/identity", {"cpf": "111.444.777-35", "phone": "(11) 97777-4321"}, t_fan)[0])

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
    listings = []
    for label, qty, price in (("Pista", 3, 14000), ("Pista Premium", 2, 22000)):
        t = types[label]
        stamp = uuid.uuid4().hex[:6].upper()
        codes = [f"MC-{stamp}-{i + 1}" for i in range(qty)]
        body, b = multipart({"ticketId": t["id"], "qty": qty, "unitPriceCents": min(price, t["faceCents"]), "codes": codes}, png())
        code, r = call("POST", f"/artists/{SLUG}/resale/events/{ev['id']}/listings", token=t_seller, headers={"content-type": "multipart/form-data; boundary=" + b}, raw=body)
        print(f"anúncio {label}:", code, "" if code == 201 else r)
        if code == 201:
            listings.append(r)
            print("  aprovado:", call("POST", f"/artists/{SLUG}/resale/admin/listings/{r['id']}/approve", {}, t_admin)[0])

    if listings:
        code, o = call("POST", f"/artists/{SLUG}/resale/listings/{listings[0]['id']}/orders", {"qty": 1}, t_fan, headers={"Idempotency-Key": uuid.uuid4().hex})
        print("reserva da fã:", code, o.get("status") if isinstance(o, dict) else o)
        if code == 201:
            code, p = call("POST", f"/artists/{SLUG}/resale/orders/{o['id']}/pay", {}, t_fan)
            print("pagamento simulado:", code, p.get("status") if isinstance(p, dict) else p)
            if code != 200:
                print("  (para pagar de mentira, ponha RESALE_ALLOW_FAKE_PAYMENT=true no .env e reinicie a API)")
    print("pronto. Abra /%s/revenda logada como a fã de teste." % SLUG)


main()
