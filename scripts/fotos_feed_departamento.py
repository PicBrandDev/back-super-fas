"""Coloca nos posts do Departamento as fotos de public/media/departamento (feed.png ... feed6.png).

Cada post oficial (Drop News) recebe uma, em rodízio. As imagens vão junto com o site (commit do front): o post
só aponta para /media/departamento/<arquivo>. Só mexe em post sem foto ou que já tem uma destas três; foto enviada por
fã ou admin fica como está. Só mexe em post sem foto ou que já tem uma destas.

Local:    PYTHONPATH=. python scripts/fotos_feed_departamento.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_feed_departamento.py
"""

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

FOTOS = [f"/media/departamento/{n}.png" for n in ("feed", "feed2", "feed3", "feed4", "feed5", "feed6")]

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == "departamento"))
    if not art:
        raise SystemExit("ambiente departamento não existe")
    # O feed do admin (/departamento/admin/mural) lista os posts oficiais (kind=drop): todos ganham foto, do mais novo ao mais antigo.
    drops = list(db.scalars(select(m.Post).where(m.Post.artist_id == art.id, m.Post.kind == "drop").order_by(m.Post.created_at.desc(), m.Post.id)))
    n = 0
    for i, p in enumerate(drops):
        if p.image_path and p.image_path not in FOTOS:
            continue  # foto enviada de verdade: não mexe
        p.image_path = FOTOS[i % len(FOTOS)]
        p.has_image = True
        n += 1
    db.commit()
    print(f"{n} posts oficiais do Departamento com foto (de {len(drops)})")
