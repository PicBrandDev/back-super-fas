"""Monta a roleta do PicKap de todos os fã clubes do Vintage Culture com 7 fatias:
2 x "Não foi dessa vez", 2 cupons de desconto no ingresso (10% e 20%), ingresso unitário de pista,
camiseta e boné (estes dois retirados na lojinha do Vintage). O que o fã ganha vai para "Meus brindes".

    PYTHONPATH=. .venv/Scripts/python scripts/mock_roleta.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_roleta.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_roleta.py

Pode rodar de novo: troca as fatias de cada fã clube pelas deste script (os brindes que o fã já ganhou ficam como estão).
"""

from sqlalchemy import delete, select

from app import models as m
from app.db import SessionLocal

ARTIST = "vintage-culture"

# rótulo, tipo, % do cupom, como retirar (vazio = texto padrão do tipo)
PRIZES = [
    ("10% no ingresso", "coupon", 10, ""),
    ("Não foi dessa vez", "none", 0, ""),
    ("Camiseta Vintage", "pickup", 0, "Retire a camiseta na lojinha do Vintage, no show, com este código e um documento com foto."),
    ("20% no ingresso", "coupon", 20, ""),
    ("Não foi dessa vez", "none", 0, ""),
    ("Boné Vintage", "pickup", 0, "Retire o boné na lojinha do Vintage, no show, com este código e um documento com foto."),
    ("Ingresso de pista", "ticket", 0, "Ingresso unitário de pista (1 pessoa). Retire na bilheteria do próximo show com este código e um documento com foto."),
]


def main() -> None:
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        clubs = list(db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id)))
        for club in clubs:
            db.execute(delete(m.Prize).where(m.Prize.club_id == club.id))
            for pos, (label, kind, percent, how) in enumerate(PRIZES):
                db.add(
                    m.Prize(
                        artist_id=artist.id, club_id=club.id, label=label, kind=kind, percent=percent, instructions=how,
                        points=0 if kind == "none" else 10, position=pos,
                    )
                )
        db.commit()
    print(f"+ roleta com {len(PRIZES)} fatias em {len(clubs)} fã clubes")


if __name__ == "__main__":
    main()
