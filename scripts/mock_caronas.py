"""Mock das caronas por show (chama a própria API; nada é escrito direto no banco).

Cria 4 motoristas de teste e, em cada show futuro, 2 ou 3 caronas (cidades, horários, vagas e preços diferentes).
A conta de fã de teste reserva e paga UMA vaga, no primeiro show (valor retido); as outras caronas ficam livres para reservar.
Precisa de CARPOOL_ALLOW_FAKE_PAYMENT=true (padrão).

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_caronas.py

Pode rodar de novo: cria caronas novas (cada motorista aceita até 3 abertas por show). Fora do container: BASE=http://localhost:8001.
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
DRIVERS = [
    ("lucas.carona@teste.com", "Lucas Ferreira", "@lucas.f", "Goiânia", "Posto Shell da BR-153", "Onix prata", 3, 4500, "Volto logo depois do show."),
    ("camila.carona@teste.com", "Camila Duarte", "@cami.d", "Brasília", "Estacionamento do Park Shopping", "HB20 branco", 2, 6000, "Aceito malas pequenas."),
    ("thiago.carona@teste.com", "Thiago Barros", "@thiago.b", "Campinas", "Terminal Rodoviário", "Corolla preto", 4, 3500, "Ar-condicionado e som bom."),
    ("renata.carona@teste.com", "Renata Lima", "@re.lima", "Belo Horizonte", "Posto Ipiranga da Via Expressa", "Kwid vermelho", 3, 5000, "Saída pontual."),
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
    today = datetime.now(timezone.utc).date()
    events = [e for e in events if e["date"] > today.isoformat()]
    if not events:
        raise SystemExit("nenhum show futuro")
    tokens = {}
    for email, name, handle, *_ in DRIVERS:
        code, _ = call("POST", "/auth/register", {"name": name, "email": email, "password": PASSWORD, "handle": handle, "artist": SLUG})
        tokens[email] = login(email)
        print(f"{name}: {'criado' if code == 201 else 'já existia'}")

    for ev in events:
        day = datetime.fromisoformat(ev["date"]).date()
        rides = []
        for i, (email, name, _h, origin, point, car, seats, price, notes) in enumerate(DRIVERS[: 2 + ord(ev["id"][0]) % 3]):
            hour = (8, 11, 14, 17)[i]
            depart = datetime.combine(day, time(hour, 0), tzinfo=timezone(timedelta(hours=-3))) - timedelta(days=1 if hour < 12 else 0)
            if depart <= datetime.now(timezone.utc) + timedelta(hours=1):
                depart = datetime.now(timezone.utc) + timedelta(days=1, hours=i)
            body = {"originCity": origin, "meetingPoint": point, "departAt": depart.isoformat(), "seats": seats, "priceCents": price, "car": car, "notes": notes}
            code, r = call("POST", f"/artists/{SLUG}/carpool/events/{ev['id']}/rides", body, tokens[email])
            print(f"{ev['city']} · {name} ({origin}):", code, "" if code == 201 else r)
            if code == 201:
                rides.append(r)
        # A fã reserva e paga só UMA vaga (no primeiro show); as demais caronas ficam livres para ela reservar.
        if ev is events[0] and rides:
            code, b = call("POST", f"/artists/{SLUG}/carpool/rides/{rides[0]['id']}/bookings", {"seats": 1}, t_fan)
            if code == 201:
                code, _ = call("POST", f"/artists/{SLUG}/carpool/bookings/{b['id']}/pay", None, t_fan)
                print("  vaga reservada e paga (retida):", code)
            else:
                print("  reserva:", code, b)


main()
