"""Coloca a arte (a foto do banner) nos anúncios de cada patrocinador.

Os arquivos têm o nome da marca em minúsculas, sem acento, com hífen no lugar do espaço (png, jpg ou webp, até 5 MB):

  nike.png                  → a arte de TODOS os anúncios da Nike
  nike__departamento.jpg    → só os anúncios da Nike no Departamento (ganha da arte geral)
  red-bull__vintage-culture.png

O que vem depois de "__" é o endereço do cantor (vintage-culture, departamento...).

  - Com a pasta (no seu computador): grava cada arquivo (no bucket, se houver; senão na pasta de uploads) e liga a arte aos anúncios.
  - Sem pasta (no servidor): só liga, no banco, as artes que já estão no bucket. O servidor não precisa dos arquivos.
Rode primeiro no seu computador (com a pasta) e depois no servidor (sem pasta).

Local:    PYTHONPATH=. python scripts/artes_anuncios.py C:\\caminho\\da\\pasta
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/artes_anuncios.py
"""

import mimetypes
import re
import sys
import unicodedata
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app import uploads
from app.config import get_settings
from app.db import SessionLocal

EXTS = (".png", ".jpg", ".jpeg", ".webp")


def slug(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


pasta = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "-" else None
if pasta is not None and not pasta.is_dir():
    raise SystemExit(f"Pasta não encontrada: {pasta}")
bucket = uploads.use_bucket()


def gravar(nome: str, dados: bytes, ext: str) -> None:
    tipo = mimetypes.types_map.get(ext, "image/png")
    if bucket:
        uploads._put(f"uploads/{nome}", dados, tipo)
    else:
        pasta_up = Path(get_settings().upload_dir)
        pasta_up.mkdir(parents=True, exist_ok=True)
        (pasta_up / nome).write_bytes(dados)


def existe(nome: str) -> bool:
    return uploads.read_bytes(nome) is not None


# arquivos da pasta: chave "marca" ou "marca__cantor" → arquivo
arquivos: dict[str, Path] = {}
if pasta is not None:
    for f in sorted(pasta.iterdir()):
        if f.is_file() and f.suffix.lower() in EXTS:
            marca, _, cantor = f.stem.partition("__")
            arquivos[f"{slug(marca)}__{slug(cantor)}" if cantor else slug(marca)] = f

with SessionLocal() as db:
    ligados = 0
    sem_arte: dict[str, int] = {}
    for c in db.scalars(select(m.Campaign).order_by(m.Campaign.created_at)):
        marca = slug(c.brand or c.sponsor.brand)
        cantor = c.slot.artist.slug
        achou = None
        for chave in (f"{marca}__{cantor}", marca):
            arq = arquivos.get(chave)
            if arq is not None:
                ext = ".jpg" if arq.suffix.lower() == ".jpeg" else arq.suffix.lower()
                nome = f"arte-{chave}{ext}"
                gravar(nome, arq.read_bytes(), ext)  # sempre regrava: trocar o arquivo da pasta troca a arte
                achou = f"/uploads/{nome}"
                break
            for ext in (".png", ".jpg", ".webp"):  # sem pasta: usa o que já está guardado
                if existe(f"arte-{chave}{ext}"):
                    achou = f"/uploads/arte-{chave}{ext}"
                    break
            if achou:
                break
        if achou:
            c.art_path = achou
            ligados += 1
        else:
            sem_arte[marca] = sem_arte.get(marca, 0) + 1
    db.commit()

print(f"{ligados} anúncios com a arte ligada")
for marca, n in sem_arte.items():
    print(f"  sem arte: {marca} ({n} anúncios) — coloque {marca}.png na pasta")
