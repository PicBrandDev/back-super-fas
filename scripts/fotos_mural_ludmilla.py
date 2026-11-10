"""Coloca foto nos posts oficiais (Drop News) da Ludmilla que ainda estão sem foto, para o admin do Mural e o Mural não ficarem só com texto.

As imagens vão junto com o site (commit do front: public/media/ludmilla/): o post só aponta para /media/ludmilla/<arquivo>.
Cada foto é casada com o assunto do post (pelo começo do texto); post que não está na lista e está sem foto recebe uma das fotos
em rodízio. Só mexe em post sem foto: foto enviada pelo admin ou por fã fica como está. Pode rodar de novo.

Local:    PYTHONPATH=. python scripts/fotos_mural_ludmilla.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_mural_ludmilla.py
"""

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

# começo do texto do post -> foto
POR_ASSUNTO = [
    ("Bi Festinha chegou", "mural-bi-festinha.jpg"),
    ("\"O Numanice começou", "mural-numanice.jpg"),
    ("Manda o vídeo", "mural-video-fa.jpg"),
    ("Coleção de óculos", "oc-cl-4926.jpg"),
    ("Datas novas na agenda", "mural-roleta-taxi.jpg"),
    ("Roleta da Lud", "oc-cl-3825.jpg"),
]
RODIZIO = ["mural-video-fa.jpg", "mural-roleta-taxi.jpg", "mural-numanice.jpg", "mural-bi-festinha.jpg"]  # a foto do palco é do post da Comunidade

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == "ludmilla"))
    if not art:
        raise SystemExit("ambiente ludmilla não existe")
    drops = list(db.scalars(select(m.Post).where(m.Post.artist_id == art.id, m.Post.kind == "drop").order_by(m.Post.created_at.desc(), m.Post.id)))
    n = outros = 0
    for p in drops:
        if p.image_path:
            continue  # já tem foto: não mexe
        arq = next((f for ini, f in POR_ASSUNTO if p.text.startswith(ini)), None)
        if not arq:
            arq = RODIZIO[outros % len(RODIZIO)]
            outros += 1
        p.image_path = f"/media/ludmilla/{arq}"
        p.has_image = True
        n += 1
        print(f"+ {arq}  <-  {p.text[:55]}")
    db.commit()
    print(f"{n} post(s) com foto; {len(drops) - n} já tinham")
