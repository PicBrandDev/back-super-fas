"""Coloca foto nos Drops (Drop News) do João Gomes que ainda estão só com texto, para o admin do Mural e o Mural não ficarem sem foto.

As imagens vão junto com o site (commit do front: public/media/joao-gomes/): o post só aponta para /media/joao-gomes/<arquivo>.
Cada foto é casada com o assunto do post (pelo começo do texto) e o Drop recebe também uma data própria (dias atrás). As datas importam:
  - o Mural abre com os 2 Drops com foto mais novos (a capa do Dominguinho e o cartaz "Abrace um Denguinho", de post_mural_joao_gomes.py),
    então os Drops daqui são mais antigos que eles;
  - o Drop também aparece na Comunidade (clube oficial, por data), e os cartazes não devem abrir a Comunidade: ficam abaixo do post
    mais novo dela (o primeiro post com foto de fã, de fotos_comunidade_joao_gomes.py).
Só mexe em Drop sem foto: foto enviada pelo admin ou outra já posta fica como está. Pode rodar de novo.

Local:    PYTHONPATH=. python scripts/fotos_mural_joao_gomes.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_mural_joao_gomes.py
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

SLUG = "joao-gomes"
# começo do texto do post -> (foto, dias atrás)
POR_ASSUNTO = [
    ("Meu Piseiro Brasileiro", "mural-piseiro.jpg", 3.2),
    ("\"Eu devo a minha vida", "mural-abraco.jpg", 5.5),
    ("Manda a foto dos forrozeiros", "mural-forrozeiros.jpg", 7.5),
    ("Loja do João no ar", "caneca-esmaltada-dominguinho.jpg", 10),
    ("Datas novas na agenda", "pin-sol-de-dominguinho.jpg", 12),
    ("Roleta do João girando", "bolsa-dois-sois.jpg", 15),
]

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if not art:
        raise SystemExit("Ambiente joao-gomes não encontrado: rode antes o criar_joao_gomes.py.")
    agora = datetime.now(timezone.utc)
    drops = list(db.scalars(select(m.Post).where(m.Post.artist_id == art.id, m.Post.kind == "drop").order_by(m.Post.created_at.desc())))
    n = 0
    for p in drops:
        if p.image_path:
            continue  # já tem foto: não mexe
        achou = next(((arq, dias) for ini, arq, dias in POR_ASSUNTO if p.text.startswith(ini)), None)
        if not achou:
            print(f"? sem foto prevista para: {p.text[:55]}")
            continue
        arq, dias = achou
        p.image_path, p.has_image, p.created_at = f"/media/joao-gomes/{arq}", True, agora - timedelta(days=dias)
        n += 1
        print(f"+ {arq}  <-  {p.text[:55]}")
    db.commit()
    print(f"{n} Drop(s) com foto")
    print("\nordem do admin do Mural (do mais novo):")
    for p in db.scalars(select(m.Post).where(m.Post.artist_id == art.id, m.Post.kind == "drop").order_by(m.Post.created_at.desc())):
        print(f"  {p.created_at:%d/%m %H:%M}  {(p.image_path or '(sem foto)').rsplit('/', 1)[-1]:<36} {p.text[:40]}")
