"""Coloca foto de perfil nas pessoas que aparecem nas telas do ambiente (rankings, feed, comentários, fã clubes).

Troca só quem está SEM foto, com o boneco gerado pelos mocks (`mock-user-*`) ou com uma foto que este script mesmo
colocou (`perfil-*`); foto que a pessoa mesma enviou não é mexida. As fotos vêm do randomuser.me (retratos feitos
para dados de teste), uma diferente para cada pessoa, baixadas e gravadas em UPLOAD_DIR. O retrato é de mulher para
nome feminino e de homem para nome masculino (pelo primeiro nome); nomes que não são de pessoa (Admin, Marca,
Patrocinador...) alternam. Precisa de internet no servidor.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_perfil.py
Só para ver quem seria trocado (não grava nada), acrescente DRY=1:
    sudo docker compose exec -T -e DRY=1 api python - < ../back-super-fas/scripts/fotos_perfil.py
"""

import os
import unicodedata
import urllib.request
import zlib
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal

SLUG = os.environ.get("ARTIST", "vintage-culture")
DRY = os.environ.get("DRY") == "1"
# Primeiros nomes dos mocks, sem acento e em minúsculas. O que não estiver aqui alterna entre mulher e homem.
FEMININOS = {"aline", "ana", "beatriz", "bia", "carla", "elisa", "gabi", "isabela", "julia", "katia", "luana", "marina", "olivia", "queila", "sofia", "ursula", "yasmin"}
MASCULINOS = {"bruno", "diego", "felipe", "gabriel", "gustavo", "henrique", "joao", "lucas", "marcos", "nicolas", "paulo", "pedro", "rafael", "thiago", "tiago", "vitor", "wesley", "zeca"}


def genero(nome: str) -> str | None:
    primeiro = unicodedata.normalize("NFD", nome.strip().split()[0].lower()) if nome.strip() else ""
    primeiro = "".join(c for c in primeiro if not unicodedata.combining(c))
    return "women" if primeiro in FEMININOS else "men" if primeiro in MASCULINOS else None


def portrait(kind: str, n: int) -> bytes:
    url = f"https://randomuser.me/api/portraits/{kind}/{n % 100}.jpg"
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
        alvo = [u for u in users if not u.avatar_path or Path(u.avatar_path).name.startswith(("mock-user-", "perfil-"))]
        print(f"{len(users)} pessoas nas telas; {len(alvo)} sem foto de verdade; {len(users) - len(alvo)} com foto própria (ficam como estão)")
        feitas, usados, indef = 0, {"women": 0, "men": 0}, 0
        for u in alvo:
            kind = genero(u.name)
            if kind is None:  # não é nome de pessoa: alterna
                kind = "women" if (usados["women"] <= usados["men"]) else "men"
                indef += 1
            n = usados[kind] = usados[kind] + 1
            if DRY:
                print(f"  trocaria: {u.name} ({u.handle or u.email}) -> {kind}")
                continue
            try:
                data = portrait(kind, n)
            except OSError as e:
                print(f"  falhou para {u.name}: {e}")
                continue
            # O nome leva um código da foto: trocar a foto muda o endereço e o navegador não usa a antiga do cache.
            name = f"perfil-{u.id}-{zlib.crc32(data):08x}.jpg"
            (folder / name).write_bytes(data)
            antiga = Path(u.avatar_path).name if u.avatar_path else ""
            u.avatar_path = f"/uploads/{name}"
            if antiga.startswith("perfil-") and antiga != name:
                (folder / antiga).unlink(missing_ok=True)
            feitas += 1
        if not DRY:
            db.commit()
            print(f"pronto: {feitas} fotos de perfil trocadas ({usados['women']} mulheres, {usados['men']} homens; {indef} nomes sem gênero definido alternaram).")


main()
