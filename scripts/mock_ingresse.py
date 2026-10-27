"""Põe a Ingresse como ticketeira de todos os shows e deixa as experiências pagas dos pacotes com preços de verdade.

Cada show ganha ticketing_name "Ingresse" e o link https://www.ingresse.com/<artista>-<cidade>-<data> (o show não tem
slug próprio, então o link é montado com o artista, a cidade e a data). Nos shows que ainda vão acontecer, todos os
pacotes ficam com as mesmas experiências avulsas, no formato de EventPackage.addons ({"key", "price_cents", "sold_out"}):
meet & greet no camarim, jantar com o Vintage, hotel com hospedagem, after e pré-esquenta. O meet & greet aparece
esgotado no primeiro pacote de cada show, para a demo mostrar o estado de esgotado.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_ingresse.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_ingresse.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_ingresse.py

Rode depois do mock_agencias.py e do mock_pacotes_experiencia.py (o popular_demo.sh já faz isso). Pode rodar de novo:
sempre grava a mesma ticketeira, o mesmo link e a mesma lista de experiências (substitui a que estiver lá).
"""

import os
import re
import unicodedata
from datetime import date

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

ARTIST = os.environ.get("ARTIST", "vintage-culture")
TICKETING_NAME = "Ingresse"
TICKETING_BASE = "https://www.ingresse.com"

# chave (ADDON_LABELS em app/defaults.py), preço extra por pessoa (R$), esgotado no primeiro pacote do show
ADDONS = [("camarim", 650, True), ("jantar", 480, False), ("hotel", 390, False), ("after", 180, False), ("pre", 120, False)]


def slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]+", "-", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip("-")


def main() -> None:
    events = packages = 0
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        for ev in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id).order_by(m.Event.date, m.Event.id)):
            ev.ticketing_name = TICKETING_NAME
            ev.ticketing_url = f"{TICKETING_BASE}/{artist.slug}-{slug(ev.city)}-{ev.date.isoformat()}"
            events += 1
            if ev.date < date.today():
                print(f"- {ev.city} ({ev.date:%d/%m}): show passado, só a ticketeira")
                continue
            for p in ev.packages:
                p.addons = [
                    {"key": key, "price_cents": price * 100, "sold_out": first_sold_out and p.position == 0}
                    for key, price, first_sold_out in ADDONS
                ]
                packages += 1
            print(f"+ {ev.city} ({ev.date:%d/%m}): Ingresse e {len(ev.packages)} pacotes com experiências")
        db.commit()
    print(f"{events} shows na Ingresse; {packages} pacotes com experiências pagas")


if __name__ == "__main__":
    main()
