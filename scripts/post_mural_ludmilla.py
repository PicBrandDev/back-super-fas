"""Cria o post oficial (Drop News) com a foto do palco que abre o Mural da Ludmilla.

A foto vai junto com o site (commit do front: public/media/ludmilla/mural-palco-grupo.jpg): o post só aponta para
/media/ludmilla/mural-palco-grupo.jpg, sem bucket. O Mural da Ludmilla mostra o Drop que tem foto como o primeiro cartaz,
com a foto inteira. Não duplica: se já existe post com essa foto, só confere. Para trocar a legenda, edite LEGENDA e rode de novo
(o script atualiza o texto do post que já existe).

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/post_mural_ludmilla.py
Local:    PYTHONPATH=. python scripts/post_mural_ludmilla.py
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

SLUG = "ludmilla"
FOTO = "/media/ludmilla/mural-palco-grupo.jpg"
LEGENDA = "Palco cheio, coreografia afinada e muito verde em volta. Marca nos comentários quem dançou junto."

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if not art:
        raise SystemExit("Ambiente ludmilla não encontrado: rode antes o criar_ludmilla.py.")
    p = db.scalar(select(m.Post).where(m.Post.artist_id == art.id, m.Post.image_path == FOTO))
    if p:
        p.text = LEGENDA
        print(f"post já existe ({p.id}); legenda conferida")
    else:
        p = m.Post(
            artist_id=art.id, kind="drop", official=True, text=LEGENDA, has_image=True, image_path=FOTO,
            likes=0, comments=0, reposts=0, views=0, created_at=datetime.now(timezone.utc),
        )
        db.add(p)
        print("post criado")
    db.commit()
