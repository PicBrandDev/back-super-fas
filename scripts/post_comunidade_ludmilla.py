"""Cria o post do fã clube oficial da Ludmilla, com a foto do palco, que abre a Comunidade.

É um post do clube oficial (não um Drop), então aparece na Comunidade como o mais novo e NÃO entra no Mural, onde o primeiro
cartaz continua sendo a foto em grupo (post_mural_ludmilla.py). O autor aparece como a artista. A foto vai junto com o site
(public/media/ludmilla/mural-agenda-palco.jpg). Não duplica: se já existe post do clube com essa foto, só confere a legenda.

Local:    PYTHONPATH=. python scripts/post_comunidade_ludmilla.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/post_comunidade_ludmilla.py
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

FOTO = "/media/ludmilla/mural-agenda-palco.jpg"
LEGENDA = "Dia de palco: luz, ensaio e a família inteira cantando junto. Quem já garantiu o próximo show?"

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == "ludmilla"))
    if not art:
        raise SystemExit("ambiente ludmilla não existe")
    clube = next((c for c in art.clubs if c.is_master), None)
    if not clube:
        raise SystemExit("A Ludmilla não tem fã clube oficial.")
    p = db.scalar(select(m.Post).where(m.Post.artist_id == art.id, m.Post.club_id == clube.id, m.Post.kind == "galera", m.Post.image_path == FOTO))
    if p:
        p.text = LEGENDA
        print(f"post já existe ({p.id}); legenda conferida")
    else:
        p = m.Post(
            artist_id=art.id, club_id=clube.id, kind="galera", official=True, text=LEGENDA, has_image=True, image_path=FOTO,
            likes=0, comments=0, reposts=0, views=0, created_at=datetime.now(timezone.utc),
        )
        db.add(p)
        print("post criado")
    db.commit()
