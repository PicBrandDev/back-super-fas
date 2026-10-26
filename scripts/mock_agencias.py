"""Cria agências parceiras, pacotes (ingressos de vários tipos e transfer) e o link da ticketeira
nos shows do Vintage Culture, para ver as telas do admin e do fã com dados.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_agencias.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_agencias.py          # Linux/Mac

Pode rodar de novo: pula os shows que já têm pacotes. Os links são de exemplo (domínio .example, reservado: não abre nenhum site).
"""

import random
import re
import unicodedata

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

AGENCIES = [
    ("Caravana Vintage", "(11) 99999-1001", "https://caravanavintage.example"),
    ("Rota Show Turismo", "contato@rotashow.example", "https://rotashow.example"),
    ("Night Express Transfer", "(21) 98888-2002", "https://nightexpress.example"),
]


def slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]+", "-", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip("-")


def main() -> None:
    rnd = random.Random(7)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        if not artist:
            raise SystemExit("O ambiente vintage-culture não existe.")
        agencies = []
        for name, contact, url in AGENCIES:
            a = db.scalar(select(m.Agency).where(m.Agency.artist_id == artist.id, m.Agency.name == name))
            if not a:
                a = m.Agency(artist_id=artist.id, name=name, contact=contact, url=url)
                db.add(a)
                db.flush()
            agencies.append(a)

        for ev in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id).order_by(m.Event.date)):
            if not ev.ticketing_url:
                ev.ticketing_name = "Ticketeira Exemplo"
                ev.ticketing_url = f"https://ticketeira.example/vintage-culture/{slug(ev.city)}"
            base = rnd.choice([150, 180, 200, 220])
            if not ev.tickets:
                for pos, (label, desc, mult) in enumerate([("Pista", "Acesso à pista", 1.0), ("Pista Premium", "Área exclusiva e bar", 1.6), ("Camarote", "Open bar e vista do palco", 2.4)]):
                    db.add(m.EventTicket(artist_id=artist.id, event_id=ev.id, label=label, description=desc, price_cents=int(base * mult) * 100, sold_out=(label == "Camarote" and rnd.random() < 0.3), position=pos))
                print(f"+ {ev.city}: ingressos avulsos criados")
            if ev.packages:
                print(f"- {ev.city}: já tem pacotes, pulei")
                continue
            agency = rnd.choice(agencies)  # cada show tem uma única agência
            # Três pacotes por show: só ingresso, ingresso + transfer e ingresso + transfer + selo no app (todos com Photo Finder).
            fee = rnd.choice([70, 90, 110])  # transfer
            seal = 40  # selo exclusivo no app do Vintage
            types = [("Pista", base), ("Pista Premium", int(base * 1.6)), ("Camarote", int(base * 2.4))]

            def sold_out(label: str) -> bool:
                return label == "Camarote" and rnd.random() < 0.25

            variants = [
                ("Somente ingresso", "Ingresso do show, sem transporte.", "ticket", lambda label, price: (label, price)),
                ("Ingresso + transfer", "Ingresso com ônibus em grupo, ida e volta.", "transfer", lambda label, price: (f"{label} + transfer", price + fee)),
                (
                    "Ingresso + transfer + selo",
                    "Ingresso, ônibus ida e volta e o selo exclusivo do show no app do Vintage.",
                    "seal",
                    lambda label, price: (f"{label} + transfer + selo", price + fee + seal),
                ),
            ]
            for pos, (name, desc, kind, build) in enumerate(variants):
                db.add(
                    m.EventPackage(
                        artist_id=artist.id,
                        event_id=ev.id,
                        agency_id=agency.id,
                        name=f"{name} · {ev.city}",
                        description=desc,
                        transfer_details="" if kind == "ticket" else f"Saída 4h antes do show, retorno 1h após o encerramento ({ev.city}).",
                        url=f"{agency.url}/vintage-culture/{slug(ev.city)}",
                        items=[
                            {"kind": kind, "label": build(label, price)[0], "price_cents": build(label, price)[1] * 100, "sold_out": sold_out(label)}
                            for label, price in types
                        ],
                        position=pos,
                    )
                )
            print(f"+ {ev.city}: pacotes criados e ticketeira configurada")
        db.commit()


if __name__ == "__main__":
    main()
