"""Cria posts de fãs com foto na Comunidade do João Gomes, espalhados entre os posts que já existem (um a cada 1-2 dias).

As 7 fotos vão junto com o site (public/media/joao-gomes/comunidade-01..07.jpg, versões leves e sem metadados das fotos originais):
o post só aponta para /media/joao-gomes/<arquivo>, sem bucket. Cada foto tem a sua legenda, escrita só com o que aparece nela.
Os autores são fãs que já participam do fã clube (as fotos se revezam entre os clubes). Não duplica: foto que já tem post é pulada.
Rode depois do popular_joao_gomes.py (precisa dos clubes e dos fãs).

Local:    PYTHONPATH=. python scripts/fotos_comunidade_joao_gomes.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_comunidade_joao_gomes.py
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

SLUG = "joao-gomes"
PASTA = "/media/joao-gomes/"
rnd = random.Random(1116)
agora = datetime.now(timezone.utc)

# arquivo, legenda, slug do fã clube de quem posta ("oficial" = clube oficial)
FOTOS = [
    ("comunidade-01.jpg", "Dia de abraço com o Treloso! A pequena não queria largar do mascote.", "forrozeiros-pe"),
    ("comunidade-02.jpg", "O momento em que ela encontrou o Treloso. Olhar de curiosidade que valeu o dia inteiro.", "forrozeiros-ba"),
    ("comunidade-03.jpg", "Animação total: a galera de mãos pro alto na brincadeira com o megafone.", "oficial"),
    ("comunidade-04.jpg", "Jantar depois do show pra fechar a noite com brinde e pão de queijo.", "forrozeiros-sp"),
    ("comunidade-05.jpg", "Pelada de domingo com os amigos e o piseiro tocando no fone.", "forrozeiros-rj"),
    ("comunidade-06.jpg", "A fila da pintura de rosto foi a mais disputada. O azul ficou show!", "forrozeiros-rs"),
    ("comunidade-07.jpg", "Foto de todo mundo junto: quando a galera se reúne, o dia fica melhor.", "forrozeiros-pe"),
]

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if not art:
        raise SystemExit("ambiente joao-gomes não existe: rode antes o criar_joao_gomes.py.")
    clubes = {("oficial" if c.is_master else c.slug): c for c in art.clubs}
    criados = 0
    for i, (arq, legenda, clube_slug) in enumerate(FOTOS):
        caminho = PASTA + arq
        if db.scalar(select(m.Post.id).where(m.Post.artist_id == art.id, m.Post.image_path == caminho)):
            print(f"já existe: {arq}")
            continue
        clube = clubes.get(clube_slug) or clubes["oficial"]
        membros = [cm.user_id for cm in db.scalars(select(m.ClubMember).where(m.ClubMember.club_id == clube.id))]
        if not membros:
            print(f"sem membros em {clube.name}: pulei {arq}")
            continue
        quando = agora - timedelta(days=1 + i * 2, hours=rnd.randint(0, 20))  # de 1 a ~13 dias atrás, entre os posts de texto
        db.add(m.Post(
            artist_id=art.id, club_id=clube.id, kind="galera", official=False, author_id=rnd.choice(membros), text=legenda,
            has_image=True, image_path=caminho, likes=rnd.randint(8, 140), comments=0, reposts=rnd.randint(0, 12),
            views=rnd.randint(120, 900), created_at=quando,
        ))
        criados += 1
        print(f"+ {arq}  ->  {clube.name}")
    db.commit()
    print(f"{criados} post(s) com foto criados")
