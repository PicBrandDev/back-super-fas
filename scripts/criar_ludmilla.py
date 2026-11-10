"""Cria o ambiente da Ludmilla (slug "ludmilla") direto no banco e já deixa no ar, com o fã clube oficial e as vitrines padrão.

É o mesmo que o admin master faz em "Novo ambiente", só que sem passar pela API (não precisa de login). Se o ambiente já existe,
só confere o status e o preço do membro. O visual vem do front (pele "ludmilla" em src/lib/brands.ts, pelo slug).

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/criar_ludmilla.py
Local:    PYTHONPATH=. python scripts/criar_ludmilla.py
Depois:   popular_ludmilla.py (dados de exemplo, só em demonstração) e anuncios_ludmilla.py (anúncios).
"""

import copy

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.defaults import BLANK_THEME, DEFAULT_MODULES, NEW_CLUB_COLORS
from app.routers.clubs import create_club
from app.routers.master import add_default_slots

SLUG = "ludmilla"

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if art is None:
        n = len(list(db.scalars(select(m.Artist.slug))))
        art = m.Artist(
            slug=SLUG, name="Ludmilla", fan_club_name="Fã clube oficial Ludmilla", instagram="@ludmilla", status="setup",
            theme=copy.deepcopy(BLANK_THEME), brand_color=NEW_CLUB_COLORS[n % len(NEW_CLUB_COLORS)], modules=dict(DEFAULT_MODULES),
        )
        db.add(art)
        db.flush()
        add_default_slots(db, art)
        create_club(db, art, "Fã clube oficial Ludmilla", is_master=True)
        print("ambiente ludmilla criado")
    else:
        print("ambiente ludmilla já existe")
    if not art.member_price_cents:
        art.member_price_cents = 1690
    art.status = "active"
    db.commit()
    print(f"ludmilla: {art.status}, membro R$ {art.member_price_cents / 100:.2f}")
