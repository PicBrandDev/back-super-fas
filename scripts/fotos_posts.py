"""Coloca foto nos posts do ambiente que estão só com texto ou com a imagem geométrica gerada pelos mocks
(feed, modal do fã, analytics dos fã clubes).

Só mexe em post SEM foto ou com imagem `mock-*`; foto enviada pelo fã ou pelo admin fica como está. As fotos vêm do
picsum.photos (imagens livres para dados de teste), uma diferente para cada post, baixadas e gravadas em UPLOAD_DIR.
Precisa de internet no servidor.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_posts.py
Só para ver quantos posts seriam trocados (não grava nada), acrescente DRY=1:
    sudo docker compose exec -T -e DRY=1 api python - < ../back-super-fas/scripts/fotos_posts.py
Para limitar a um tipo de post (drop, galera, instagram): KIND=galera.
"""

import os
import urllib.request
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal

SLUG = os.environ.get("ARTIST", "vintage-culture")
DRY = os.environ.get("DRY") == "1"
KIND = os.environ.get("KIND", "")


def photo(seed: str) -> bytes:
    req = urllib.request.Request(f"https://picsum.photos/seed/{seed}/800/800.jpg", headers={"User-Agent": "super-fas-mock/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main() -> None:
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
        if not artist:
            raise SystemExit(f"ambiente {SLUG} não existe")
        club_ids = [c.id for c in db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id))]
        posts = list(db.scalars(select(m.Post).where((m.Post.artist_id == artist.id) | (m.Post.club_id.in_(club_ids)))))
        alvo = [p for p in posts if (not p.image_path or Path(p.image_path).name.startswith("mock-")) and (not KIND or p.kind == KIND)]
        print(f"{len(posts)} posts; {len(alvo)} sem foto de verdade{' (' + KIND + ')' if KIND else ''}; {len(posts) - len(alvo)} ficam como estão")
        if DRY:
            return
        feitas = 0
        for p in alvo:
            try:
                data = photo(p.id)
            except OSError as e:
                print(f"  falhou no post {p.id}: {e}")
                continue
            name = f"post-{p.id}.jpg"
            (folder / name).write_bytes(data)
            p.image_path = f"/uploads/{name}"
            p.has_image = True
            feitas += 1
        db.commit()
        print(f"pronto: {feitas} posts com foto.")


main()
