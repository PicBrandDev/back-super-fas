"""Cria patrocinadores e aluguéis de vitrine de exemplo (campanhas aprovadas, no ar, agendadas e encerradas),
com preço por semana nas vitrines, para a tela "Vitrines alugadas" do admin.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_vitrines.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_vitrines.py          # Linux/Mac

Pode rodar de novo: pula as campanhas de exemplo que já existem.
"""

import random
from datetime import date, timedelta

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

BRANDS = [
    ("Marca Aurora", "aurora@patrocinio.example"),
    ("Beats Sul", "beats@patrocinio.example"),
    ("Festa Zero", "festazero@patrocinio.example"),
    ("Ótica Lume", "lume@patrocinio.example"),
    ("Café Nobre", "nobre@patrocinio.example"),
    ("Tênis Pulse", "pulse@patrocinio.example"),
]
# (dias até o início, duração em dias): negativo = já começou; tudo encerrado fica no passado
WINDOWS = [(-5, 21), (-12, 14), (-2, 28), (6, 14), (15, 21), (-60, 30), (-90, 14)]


def main() -> None:
    rnd = random.Random(5)
    today = date.today()
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        if not artist:
            raise SystemExit("O ambiente vintage-culture não existe.")
        slots = sorted(artist.ad_slots, key=lambda s: (s.club_id is not None, s.position))
        if not slots:
            raise SystemExit("O ambiente não tem vitrines.")
        for s in slots:  # preço por semana (em centavos), só nas que ainda não têm
            if s.price_cents is None:
                s.price_cents = rnd.choice([40000, 60000, 80000, 120000])
        sponsors = []
        for brand, email in BRANDS:
            sp = db.scalar(select(m.Sponsor).where(m.Sponsor.email == email))
            if not sp:
                sp = m.Sponsor(brand=brand, email=email, status="active")
                db.add(sp)
                db.flush()
            sponsors.append(sp)
        added = 0
        for i, (offset, length) in enumerate(WINDOWS):
            sp = sponsors[i % len(sponsors)]
            slot = slots[(i * 2) % len(slots)]
            title = f"Campanha {sp.brand} {i + 1}"
            if db.scalar(select(m.Campaign).where(m.Campaign.title == title)):
                continue
            start = today + timedelta(days=offset)
            db.add(
                m.Campaign(
                    sponsor_id=sp.id, slot_id=slot.id, brand=sp.brand, title=title, text="Anúncio de exemplo.",
                    start=start, end=start + timedelta(days=length - 1), status="approved",
                )
            )
            added += 1
        db.commit()
        print(f"+ {added} aluguéis de vitrine de exemplo")


if __name__ == "__main__":
    main()
