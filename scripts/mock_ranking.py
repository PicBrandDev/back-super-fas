"""Cria compartilhamentos de exemplo (já confirmados) para os fãs de exemplo, para ver o ranking Fã Super
geral e o de cada fã clube com dados.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_ranking.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_ranking.py          # Linux/Mac

Pode rodar de novo: pula os fãs que já têm compartilhamentos de exemplo. Os links são de domínio reservado (.example).
"""

import colorsys
import random
import struct
import zlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import instagram, models as m
from app.config import get_settings
from app.db import SessionLocal

ARTIST = "vintage-culture"


def avatar_png(seed: int, size: int = 96) -> bytes:
    """Fotinha de perfil de exemplo: fundo colorido com um busto estilizado (sem depender de Pillow)."""
    rnd = random.Random(seed)
    hue = rnd.random()
    bg = [int(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.55, 0.8)]
    fg = [int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.5) % 1, 0.25, 0.97)]
    c = size / 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            head = (x - c) ** 2 + (y - size * 0.38) ** 2 < (size * 0.18) ** 2
            body = (x - c) ** 2 / (size * 0.34) ** 2 + (y - size * 0.98) ** 2 / (size * 0.42) ** 2 < 1
            row += bytes(fg if head or body else bg)
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return bytes([137]) + b"PNG" + bytes([13, 10, 26, 10]) + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


def main() -> None:
    rnd = random.Random(11)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit("O ambiente vintage-culture não existe.")
        fans = [u for u in db.scalars(select(m.User).where(m.User.role == m.ROLE_FAN)) if u.email.endswith("@exemplo.com")]
        upload_dir = __import__("pathlib").Path(get_settings().upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        for u in fans:
            if not u.avatar_path:
                name = f"mock-user-{u.id}.png"
                (upload_dir / name).write_bytes(avatar_png(hash(u.id) & 0xFFFF))
                u.avatar_path = f"/uploads/{name}"
        n_users = n_shares = 0
        for u in fans:
            f = db.scalar(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == u.id))
            if not f:
                continue
            if db.scalar(select(m.InstagramShare).where(m.InstagramShare.user_id == u.id, m.InstagramShare.media_id.like("mock-%"))):
                continue
            instagram.share_code(db, f)
            # Poucos fãs com muitos compartilhamentos e muitos com poucos (cauda longa); alguns sem nenhum.
            total = max(0, int(rnd.paretovariate(1.4)) - 1)
            total = min(total, 25) if rnd.random() < 0.75 else 0
            for i in range(total):
                when = now - timedelta(days=rnd.randint(0, 20), hours=rnd.randint(0, 23))
                db.add(
                    m.InstagramShare(
                        artist_id=artist.id,
                        user_id=u.id,
                        status="verified",
                        media_id=f"mock-{u.id}-{i}",
                        permalink=f"https://instagram.example/p/{u.id}{i}",
                        created_at=when,
                        verified_at=when,
                    )
                )
            n_users += 1
            n_shares += total
        db.commit()
        print(f"+ {n_shares} compartilhamentos confirmados para {n_users} fãs de exemplo")


if __name__ == "__main__":
    main()
