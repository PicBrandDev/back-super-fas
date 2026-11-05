"""Coloca nos posts do Departamento as fotos de public/media/departamento (feed.png, feed2.png, feed3.png).

Um post sim, outro não, em rodízio (feed, feed2, feed3, feed...). As imagens vão junto com o site (commit do front): o post
só aponta para /media/departamento/<arquivo>. Só mexe em post sem foto ou que já tem uma destas três; foto enviada por
fã ou admin fica como está.

Local:    PYTHONPATH=. python scripts/fotos_feed_departamento.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_feed_departamento.py
"""

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

FOTOS = ["/media/departamento/feed.png", "/media/departamento/feed2.png", "/media/departamento/feed3.png"]

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == "departamento"))
    if not art:
        raise SystemExit("ambiente departamento não existe")
    posts = list(db.scalars(select(m.Post).where(m.Post.artist_id == art.id).order_by(m.Post.created_at, m.Post.id)))
    n = 0
    for i, p in enumerate(posts):
        if p.image_path and p.image_path not in FOTOS:
            continue  # foto enviada de verdade: não mexe
        if i % 2 == 0:
            p.image_path = FOTOS[(i // 2) % len(FOTOS)]
            p.has_image = True
            n += 1
        elif p.image_path in FOTOS:
            p.image_path = ""
            p.has_image = False
    db.commit()
    print(f"{n} posts do Departamento com foto (de {len(posts)})")
