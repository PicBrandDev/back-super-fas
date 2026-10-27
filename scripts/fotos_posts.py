"""Coloca foto do Vintage Culture nos posts do ambiente que estão só com texto ou com uma imagem gerada/sorteada.

Usa as fotos que o próprio app publica em /media/vintage-culture: fotos de imprensa do artista, camisetas da loja e
17 fotos de palco, cabine de DJ e público de festival (feed/, com os créditos em feed/CREDITOS.md). Os Drop News
alternam entre fotos do artista e de palco (o mais novo ganha a primeira); posts que falam de camiseta/loja/merch ganham foto de camiseta;
os posts da galera alternam entre as fotos de festival. As fotos vão em rodízio, uma depois da outra, então posts
seguidos nunca repetem a foto. São baixadas do site do app (FRONT_URL) e gravadas em UPLOAD_DIR: precisa de internet.

Só mexe em post SEM foto ou com imagem gerada (`mock-*`, `post-*` do picsum, `vc-*` deste script); foto enviada pelo
fã ou pelo admin fica como está. Para ter ainda mais variedade, junte mais fotos em /media/vintage-culture/feed e
acrescente o nome em FEED.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_posts.py
Só para ver quantos posts seriam trocados (não grava nada), acrescente DRY=1:
    sudo docker compose exec -T -e DRY=1 api python - < ../back-super-fas/scripts/fotos_posts.py
Para outro endereço do front (teste local): FRONT_URL=http://localhost:3000. Para limitar a um tipo: KIND=galera.
"""

import os
import re
import urllib.request
import zlib
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal

SLUG = os.environ.get("ARTIST", "vintage-culture")
DRY = os.environ.get("DRY") == "1"
KIND = os.environ.get("KIND", "")
FRONT_URL = os.environ.get("FRONT_URL", "https://fa-clube.picbrand.com.br").rstrip("/")

# Fotos do artista (palco, estúdio, bastidor) e da loja, todas em /media/vintage-culture do front.
FOTOS = ["artist.jpg", "press-1.webp", "press-2.webp", "press-3.jpg", "press-4.webp"]
# Na ordem do rodízio: fotos parecidas (as da mesma cabine de DJ) ficam longe uma da outra.
FEED = [f"feed/feed-{n:02d}.jpg" for n in (1, 5, 6, 2, 9, 10, 7, 3, 11, 13, 8, 4, 12, 14, 15, 16, 17)]
LOJA = ["tee-93.jpg", "tee-bootleg.jpg", "tee-lost.jpg", "tee-vntg77.jpg", "store-1.webp", "store-lost-verso.webp"]
FALA_DE_LOJA = re.compile(r"camiseta|camisa|merch|bootleg|\btee\b|vntg|loja|ver[ãa]o|lost", re.I)
GERADAS = ("mock-", "post-", "vc-")

_cache: dict[str, bytes] = {}


def baixar(arquivo: str) -> tuple[bytes, str]:
    if arquivo not in _cache:
        req = urllib.request.Request(f"{FRONT_URL}/media/vintage-culture/{arquivo}", headers={"User-Agent": "super-fas-mock/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            _cache[arquivo] = r.read()
    return _cache[arquivo], Path(arquivo).suffix


def intercalar(a: list[str], b: list[str]) -> list[str]:
    """Uma de cada lista, na ordem (a, b, a, b...), até acabar as duas."""
    out: list[str] = []
    for i in range(max(len(a), len(b))):
        out += [x[i] for x in (a, b) if i < len(x)]
    return out


def escolher(post: m.Post, contador: dict[str, int]) -> str:
    """Rodízio por tipo de post: a cada post a próxima foto da lista, para posts seguidos não repetirem."""
    if FALA_DE_LOJA.search(post.text or ""):
        grupo, lista = "loja", LOJA
    elif post.kind == "drop":
        grupo, lista = "drop", intercalar(FOTOS, FEED)  # Drop News: o artista e o palco, do mais novo para o mais antigo
    elif post.official:
        grupo, lista = "oficial", intercalar(FEED, FOTOS)
    else:
        grupo, lista = "galera", FEED
    n = contador[grupo] = contador.get(grupo, -1) + 1
    return lista[n % len(lista)]


def main() -> None:
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
        if not artist:
            raise SystemExit(f"ambiente {SLUG} não existe")
        club_ids = [c.id for c in db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id))]
        posts = list(db.scalars(select(m.Post).where((m.Post.artist_id == artist.id) | (m.Post.club_id.in_(club_ids)))))
        alvo = [p for p in posts if (not p.image_path or Path(p.image_path).name.startswith(GERADAS)) and (not KIND or p.kind == KIND)]
        print(f"{len(posts)} posts; {len(alvo)} sem foto de verdade{' (' + KIND + ')' if KIND else ''}; {len(posts) - len(alvo)} ficam como estão")
        if DRY:
            return
        feitas, contador = 0, {}
        for p in sorted(alvo, key=lambda p: p.created_at, reverse=True):
            try:
                data, ext = baixar(escolher(p, contador))
            except OSError as e:
                print(f"  falhou no post {p.id}: {e}")
                continue
            antiga = Path(p.image_path).name if p.image_path else ""
            name = f"vc-{p.id}-{zlib.crc32(data):08x}{ext}"  # o código muda o endereço: o navegador não usa a foto antiga do cache
            (folder / name).write_bytes(data)
            p.image_path = f"/uploads/{name}"
            p.has_image = True
            if antiga.startswith(("post-", "vc-")) and antiga != name:
                (folder / antiga).unlink(missing_ok=True)
            feitas += 1
        db.commit()
        print(f"pronto: {feitas} posts com foto do Vintage Culture.")


main()
