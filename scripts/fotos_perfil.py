"""Coloca foto de perfil nas pessoas que aparecem nas telas do ambiente (rankings, feed, comentários, fã clubes).

Troca só quem está SEM foto ou com o boneco gerado pelos mocks (`mock-user-*`); foto que a pessoa mesma enviou
não é mexida. As fotos vêm do randomuser.me (retratos feitos para dados de teste), uma diferente para cada pessoa,
baixadas e gravadas em UPLOAD_DIR. Precisa de internet no servidor.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_perfil.py
Só para ver quem seria trocado (não grava nada), acrescente DRY=1:
    sudo docker compose exec -T -e DRY=1 api python - < ../back-super-fas/scripts/fotos_perfil.py
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
SOURCES = ("women", "men")  # alterna, para o ranking não ficar com uma foto só de um tipo


def portrait(n: int) -> bytes:
    url = f"https://randomuser.me/api/portraits/{SOURCES[n % 2]}/{(n // 2) % 100}.jpg"
    req = urllib.request.Request(url, headers={"User-Agent": "super-fas-mock/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
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
        ids = {p.author_id for p in posts if p.author_id}
        if posts:
            ids |= {c.author_id for c in db.scalars(select(m.PostComment).where(m.PostComment.post_id.in_([p.id for p in posts]))) if c.author_id}
        ids |= {s.user_id for s in db.scalars(select(m.InstagramShare).where(m.InstagramShare.artist_id == artist.id))}
        if club_ids:
            ids |= {s.user_id for s in db.scalars(select(m.ClubStaff).where(m.ClubStaff.club_id.in_(club_ids)))}
            ids |= {mb.user_id for mb in db.scalars(select(m.ClubMember).where(m.ClubMember.club_id.in_(club_ids)))}
        users = sorted(db.scalars(select(m.User).where(m.User.id.in_(ids))), key=lambda u: u.id) if ids else []
        alvo = [u for u in users if not u.avatar_path or Path(u.avatar_path).name.startswith("mock-user-")]
        print(f"{len(users)} pessoas nas telas; {len(alvo)} sem foto de verdade; {len(users) - len(alvo)} com foto própria (ficam como estão)")
        feitas = 0
        for n, u in enumerate(alvo):
            if DRY:
                print(f"  trocaria: {u.name} ({u.handle or u.email})")
                continue
            try:
                data = portrait(n)
            except OSError as e:
                print(f"  falhou para {u.name}: {e}")
                continue
            name = f"perfil-{u.id}.jpg"
            (folder / name).write_bytes(data)
            u.avatar_path = f"/uploads/{name}"
            feitas += 1
        if not DRY:
            db.commit()
            print(f"pronto: {feitas} fotos de perfil trocadas.")


main()
