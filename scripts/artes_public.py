"""Liga aos anúncios de cada patrocinador as artes que estão na pasta public/patrocinadores do front.

As imagens vão junto com o site (commit do front): este script só aponta cada anúncio da marca para elas, sem bucket.
Se a marca tem mais de uma arte, elas se revezam entre os anúncios dela (1º anúncio = 1ª arte, 2º = 2ª, ...).
Para acrescentar outra marca, ponha as imagens em public/patrocinadores e liste os caminhos em ARTES.

Local:    PYTHONPATH=. python scripts/artes_public.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/artes_public.py
"""

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

ARTES = {
    "Heineken": ["/patrocinadores/anuncio1.png", "/patrocinadores/anuncio2.png", "/patrocinadores/anuncio3.png"],
    "Nike": [f"/patrocinadores/nike_anuncio{i}.png" for i in range(1, 7)],
    "Sprite": [f"/patrocinadores/sprite_anuncio{i}.png" for i in range(1, 4)],
    "Coca-Cola": ["/patrocinadores/coca_anuncio1.png"],
    "Adidas": [f"/patrocinadores/adidas_anuncio{i}.png" for i in range(1, 4)],
}

with SessionLocal() as db:
    for marca, artes in ARTES.items():
        camps = list(db.scalars(select(m.Campaign).where(m.Campaign.brand == marca).order_by(m.Campaign.created_at, m.Campaign.id)))
        camps = [c for c in camps if not c.video_url]  # anúncio em vídeo mantém a capa dele
        for i, c in enumerate(camps):
            c.art_path = artes[i % len(artes)]
            print(f"{marca}: {c.slot.artist.name} - {c.slot.name} -> {c.art_path}")
        if not camps:
            print(f"{marca}: sem anúncios")
    db.commit()
print("pronto")
