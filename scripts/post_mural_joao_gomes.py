"""Cria os posts oficiais (Drop News) com foto que abrem o Mural do João Gomes: a capa do Dominguinho e o cartaz "Abrace um Denguinho".

As fotos vão junto com o site (commit do front: public/media/joao-gomes/mural1.jpg e mural.jpg): o post só aponta para
/media/joao-gomes/<arquivo>, sem bucket. O Mural mostra os 2 Drops mais novos com foto (a pele do João Gomes tem `postPhoto: 2`),
o mais novo primeiro, com a foto inteira. O Drop também aparece na Comunidade (como post do clube oficial, ordenado por data);
por isso as datas são de alguns dias atrás: eles abrem o Mural sem ficar no topo da Comunidade. A ordem do Mural é a das datas
(mural1 mais novo que mural). Não duplica: se já existe post com a foto, só confere a legenda e a data. Para trocar uma legenda,
edite POSTS e rode de novo.

Local:    PYTHONPATH=. python scripts/post_mural_joao_gomes.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/post_mural_joao_gomes.py
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

SLUG = "joao-gomes"
# (foto, legenda, quantos dias atrás). A primeira palavra da legenda vira a manchete por cima da foto.
# Dias atrás: os 2 cartazes são os Drops mais novos (abrem o Mural) mas ficam abaixo do 1º post da Comunidade (fotos de fãs, de 1 dia em diante); mural1 mais novo que mural.
POSTS = [
    ("/media/joao-gomes/mural1.jpg", "Ouça o Dominguinho: João Gomes, Mestrinho e Jota.Pê. Já deu o play?", 2.5),
    ("/media/joao-gomes/mural.jpg", "Abrace um Denguinho: um dia de diversão em prol do Hospital Dom Tomás, no Parque Josefa Coelho, em Petrolina (PE). Quem abraçou a causa?", 2.6),
]

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if not art:
        raise SystemExit("Ambiente joao-gomes não encontrado: rode antes o criar_joao_gomes.py.")
    agora = datetime.now(timezone.utc)
    for foto, legenda, dias in POSTS:
        quando = agora - timedelta(days=dias)
        p = db.scalar(select(m.Post).where(m.Post.artist_id == art.id, m.Post.image_path == foto))
        if p:
            p.text, p.created_at = legenda, quando
            print(f"já existe ({p.id}): {foto}; legenda e data conferidas")
        else:
            db.add(m.Post(
                artist_id=art.id, kind="drop", official=True, text=legenda, has_image=True, image_path=foto,
                likes=0, comments=0, reposts=0, views=0, created_at=quando,
            ))
            print(f"post criado: {foto}")
    db.commit()
    print("\nordem do Mural (Drops com foto, do mais novo):")
    for p in db.scalars(select(m.Post).where(m.Post.artist_id == art.id, m.Post.kind == "drop", m.Post.image_path != "").order_by(m.Post.created_at.desc())):
        print(f"  {p.created_at:%d/%m %H:%M}  {p.image_path}")
