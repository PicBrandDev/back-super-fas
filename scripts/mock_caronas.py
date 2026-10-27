"""Mock das caronas por show (chama a própria API; nada é escrito direto no banco).

Cria exatamente 10 caronas nos shows futuros, TODAS já com reservas pagas (Pix ou cartão):
  - 4 motoristas de teste (Lucas, Camila, Thiago, Renata) e a conta de fã de teste, que também lança uma carona;
  - 4 passageiros de teste (Ana, Bruno, Carla, Diego), no máximo uma reserva por show cada;
  - a conta de fã de teste reserva e paga UMA vaga (na carona da Camila, no segundo show); no primeiro show ela só oferece, e sobra a carona do Lucas para reservar.
Precisa de CARPOOL_ALLOW_FAKE_PAYMENT=true (padrão).

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_caronas.py

Só cria se ainda não houver caronas dos motoristas de teste (não duplica). Para refazer do zero, limpe antes:
    sudo docker compose exec -T api python - < ../back-super-fas/scripts/limpar_caronas_mock.py
Fora do container: BASE=http://localhost:8001 (e PYTHONPATH=. para o script de limpeza).
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone

BASE = os.environ.get("BASE", "http://localhost:8000")
SLUG = os.environ.get("ARTIST", "vintage-culture")
PASSWORD = os.environ.get("CONTAS_SENHA", "senha123")
FAN = "juliacristinalopes2607@gmail.com"
# email, nome, @, cidade de saída, endereço da saída, carro, vagas, preço (centavos), observação
DRIVERS = [
    ("lucas.carona@teste.com", "Lucas Ferreira", "@lucas.f", "Goiânia", "Posto Shell, BR-153 km 4, Setor Pedro Ludovico, Goiânia - GO", "Onix prata", 3, 4500, "Volto logo depois do show."),
    ("camila.carona@teste.com", "Camila Duarte", "@cami.d", "Brasília", "Park Shopping, Área Especial 2, Setor Industrial Sul, Brasília - DF", "HB20 branco", 3, 6000, "Aceito malas pequenas."),
    ("thiago.carona@teste.com", "Thiago Barros", "@thiago.b", "Campinas", "Terminal Rodoviário de Campinas, Rua Mogi Mirim 1000, Centro, Campinas - SP", "Corolla preto", 4, 3500, "Ar-condicionado e som bom."),
    ("renata.carona@teste.com", "Renata Lima", "@re.lima", "Belo Horizonte", "Posto Ipiranga, Av. Cristiano Machado 4000, Belo Horizonte - MG", "Kwid vermelho", 3, 5000, "Saída pontual."),
]
FAN_RIDE = ("São Paulo", "Av. Paulista 1000, Bela Vista, São Paulo - SP", "Civic cinza", 4, 5500, "Saio cedo e volto depois do show.")
PAX = [
    ("ana.carona@teste.com", "Ana Beatriz", "@ana.bea"),
    ("bruno.carona@teste.com", "Bruno Alves", "@bruno.a"),
    ("carla.carona@teste.com", "Carla Mendes", "@carla.m"),
    ("diego.carona@teste.com", "Diego Rocha", "@diego.r"),
]
# (índice do show, motorista (índice em DRIVERS ou "fan"), passageiros (índices em PAX))
PLAN = [
    (0, "fan", [0, 1]),
    (0, 0, [2]),
    (1, 1, [0, 1]),
    (1, 2, [2, 3]),
    (2, 3, [0]),
    (2, 0, [1, 2]),
    (3, 1, [0, 1]),
    (4, 2, [0]),
    (5, 3, [0, 1]),
    (5, 0, [2]),
]


def call(method, path, body=None, token=None):
    h = {"content-type": "application/json"} if body is not None else {}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
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


def main():
    t_fan = login(FAN)
    code, events = call("GET", f"/artists/{SLUG}/events", None, t_fan)
    now = datetime.now(timezone.utc)
    events = sorted((e for e in events if e["date"] > now.date().isoformat()), key=lambda e: e["date"])
    if not events:
        raise SystemExit("nenhum show futuro")

    tokens = {}
    for email, name, handle, *_ in DRIVERS:
        call("POST", "/auth/register", {"name": name, "email": email, "password": PASSWORD, "handle": handle, "artist": SLUG})
        tokens[email] = login(email)
    for email, name, handle in PAX:
        call("POST", "/auth/register", {"name": name, "email": email, "password": PASSWORD, "handle": handle, "artist": SLUG})
        tokens[email] = login(email)

    if any(call("GET", f"/artists/{SLUG}/carpool/me", None, tokens[d[0]])[1]["offered"] for d in DRIVERS):
        raise SystemExit("Já existem caronas dos motoristas de teste: nada foi criado (limpe antes com limpar_caronas_mock.py).")

    n = 0
    for k, (ei, who, pax) in enumerate(PLAN):
        ev = events[ei % len(events)]
        if who == "fan":
            email, token = FAN, t_fan
            origin, point, car, seats, price, notes = FAN_RIDE[0], FAN_RIDE[1], FAN_RIDE[2], FAN_RIDE[3], FAN_RIDE[4], FAN_RIDE[5]
        else:
            email, _name, _h, origin, point, car, seats, price, notes = DRIVERS[who]
            token = tokens[email]
        day = datetime.fromisoformat(ev["date"]).date()
        depart = datetime.combine(day, time((8, 10, 13, 16)[k % 4], 0), tzinfo=timezone(timedelta(hours=-3))) - timedelta(days=1)
        if depart <= now + timedelta(hours=1):
            depart = now + timedelta(days=1, hours=k)
        body = {"originCity": origin, "meetingPoint": point, "departAt": depart.isoformat(), "seats": seats, "priceCents": price, "car": car, "notes": notes}
        code, ride = call("POST", f"/artists/{SLUG}/carpool/events/{ev['id']}/rides", body, token)
        print(f"{ev['city']} · {origin} ({email.split('@')[0]}):", code, "" if code == 201 else ride)
        if code != 201:
            continue
        n += 1
        passengers = [(PAX[i][0], tokens[PAX[i][0]]) for i in pax]
        if ei == 1 and who == 1:  # a conta de fã de teste reserva a única vaga dela nesta carona (no show 1)
            passengers.append((FAN, t_fan))
        for j, (pe, pt) in enumerate(passengers):
            code, b = call("POST", f"/artists/{SLUG}/carpool/rides/{ride['id']}/bookings", {"seats": 1}, pt)
            if code == 201:
                code, _ = call("POST", f"/artists/{SLUG}/carpool/bookings/{b['id']}/pay", {"method": "pix" if (k + j) % 2 == 0 else "cartao"}, pt)
            print("   reserva", pe.split("@")[0], "paga:", code)
    print(f"{n} caronas criadas.")


main()
