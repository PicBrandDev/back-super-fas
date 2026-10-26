"""Dá foto aos posts do Drop News (mural oficial do artista) que não têm e completa até 8 posts, cada um com foto,
curtidas, comentários e visualizações. Aparecem em Admin > Drop News e em Mural > Cartazes do app.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_dropnews.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_dropnews.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_dropnews.py

Pode rodar de novo: só mexe nos posts sem foto e só cria o que falta para chegar a 8.
"""

import colorsys
import random
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal

ARTIST = "vintage-culture"
TARGET = 8

NEW_POSTS = [
    "Fanzone no ar! Prévias exclusivas, roleta do PicKup e fotos oficiais dos shows, tudo num lugar só.",
    "Próxima parada: São Paulo, 07 de novembro. Pacotes com transfer e selo no app já estão à venda.",
    "Fotos oficiais do show de Campinas liberadas. Mande uma selfie no Photo Finder e encontre as suas.",
    "Bastidores da turnê: soundcheck, estrada e muita história. Em breve, mais aqui no mural.",
    "A roleta do PicKup tem prêmio novo: camiseta Tour 2026. Quem ganhar mostra aqui!",
    "Quem postou com a #EuSouUmSuperFaDoVintage esta semana subiu no ranking Fã Super. Confiram a lista.",
    "Vocês são o melhor público do Brasil. Sem exagero.",
    "Drop novo na área: Faixa inédita 01 já está no Drops Hits. Corre ouvir.",
]


def photo_png(seed: int, w: int = 288, h: int = 360) -> bytes:
    """Arte abstrata em tons quentes e frios (faixas e um disco), só para ilustrar posts de exemplo."""
    rnd = random.Random(seed)
    hue = rnd.random()
    c1 = [int(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.65, 0.35)]
    c2 = [int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.08) % 1, 0.75, 0.95)]
    c3 = [int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.5) % 1, 0.5, 0.9)]
    cx, cy, rad = rnd.randint(w // 4, 3 * w // 4), rnd.randint(h // 3, 2 * h // 3), rnd.randint(w // 6, w // 3)
    band = rnd.randint(18, 48)
    rows = []
    for y in range(h):
        row = bytearray([0])
        t = y / h
        for x in range(w):
            if (x - cx) ** 2 + (y - cy) ** 2 < rad**2:
                col = c3
            elif ((x + y) // band) % 2 == 0:
                col = [int(c1[i] * (1 - t) + c2[i] * t * 0.55) for i in range(3)]
            else:
                col = [int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)]
            row += bytes(col)
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return bytes([137]) + b"PNG" + bytes([13, 10, 26, 10]) + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b"")


def main() -> None:
    rnd = random.Random(31)
    now = datetime.now(timezone.utc)
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        posts = list(db.scalars(select(m.Post).where(m.Post.artist_id == artist.id, m.Post.kind == "drop", m.Post.club_id.is_(None))))

        def attach(post: m.Post) -> None:
            name = f"mock-drop-{post.id}.png"
            (folder / name).write_bytes(photo_png(rnd.randint(0, 100_000)))
            post.image_path, post.has_image = f"/uploads/{name}", True

        with_photo = 0
        for p in posts:
            if not p.image_path:
                attach(p)
                with_photo += 1

        created = 0
        texts = [t for t in NEW_POSTS if not any(p.text == t for p in posts)]
        for text in texts[: max(0, TARGET - len(posts))]:
            likes = rnd.randint(800, 3200)
            p = m.Post(
                artist_id=artist.id, kind="drop", club_id=None, official=True, text=text, likes=likes,
                comments=rnd.randint(20, 400), reposts=rnd.randint(30, 600), views=likes * rnd.randint(4, 9),
                created_at=now - timedelta(days=rnd.randint(0, 14), hours=rnd.randint(0, 20)),
            )
            db.add(p)
            db.flush()
            attach(p)
            created += 1
        db.commit()
    print(f"+ {with_photo} posts do Drop News ganharam foto e {created} posts novos foram criados")


if __name__ == "__main__":
    main()
