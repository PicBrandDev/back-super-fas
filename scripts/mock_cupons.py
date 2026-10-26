"""Dá a todo fã e dono de fã clube do ambiente o cupom ROLETA10 (10% de desconto no ingresso, uso único), como se
tivesse sido ganho na roleta do PicKup. Aparece no carrinho de compra em "Meus cupons".

    PYTHONPATH=. .venv/Scripts/python scripts/mock_cupons.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_cupons.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_cupons.py

Pode rodar de novo: pula quem já tem o cupom. Contas de admin master e de patrocinador não entram.
"""

from sqlalchemy import select

from app import models as m
from app.coupons import ROULETTE_CODE
from app.db import SessionLocal

ARTIST = "vintage-culture"


def main() -> None:
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        added = 0
        for u in db.scalars(select(m.User).where(m.User.role.in_([m.ROLE_FAN, m.ROLE_ARTIST_ADMIN]))):
            if db.scalar(select(m.Coupon.id).where(m.Coupon.artist_id == artist.id, m.Coupon.user_id == u.id, m.Coupon.code == ROULETTE_CODE)):
                continue
            db.add(m.Coupon(artist_id=artist.id, user_id=u.id, code=ROULETTE_CODE, kind="percent", value=10, max_uses=1, source="Prêmio da roleta do PicKup"))
            added += 1
        db.commit()
    print(f"+ {added} cupons {ROULETTE_CODE} (10% de desconto, uso único)")


if __name__ == "__main__":
    main()
