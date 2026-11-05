"""Coloca o logo (a foto de perfil) de cada patrocinador.

Os logos são arquivos com o nome da marca em minúsculas e sem acento, com hífen no lugar do espaço: nike.png, red-bull.jpg,
coca-cola.webp, spotify.png... (png, jpg ou webp, até 5 MB).

  - Com a pasta dos logos (no seu computador): envia cada arquivo para o bucket (`uploads/logo-<marca>.<ext>`) e grava o logo no banco.
  - Sem pasta (no servidor): só liga, no banco, os logos que já estão no bucket. Assim o servidor não precisa dos arquivos.
Rode primeiro no seu computador (com a pasta) e depois no servidor (sem pasta).

Local:    PYTHONPATH=. python scripts/logos_patrocinadores.py C:\caminho\da\pasta
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/logos_patrocinadores.py
"""

import mimetypes
import re
import sys
import unicodedata
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app import uploads
from app.db import SessionLocal

EXTS = (".png", ".jpg", ".jpeg", ".webp")


def slug(marca: str) -> str:
    s = unicodedata.normalize("NFKD", marca).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


pasta = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "-" else None
if pasta is not None and not pasta.is_dir():
    raise SystemExit(f"Pasta não encontrada: {pasta}")
if not uploads.use_bucket():
    raise SystemExit("O bucket não está configurado (UPLOADS_S3_BUCKET): os logos precisam ir para ele.")

with SessionLocal() as db:
    for sp in db.scalars(select(m.Sponsor).order_by(m.Sponsor.brand)):
        nome = slug(sp.brand)
        if pasta is not None:
            arq = next((f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in EXTS and slug(f.stem) == nome), None)
            if arq is not None:
                ext = ".jpg" if arq.suffix.lower() == ".jpeg" else arq.suffix.lower()
                uploads._put(f"uploads/logo-{nome}{ext}", arq.read_bytes(), mimetypes.types_map.get(ext, "image/png"))
                print(f"{sp.brand}: logo enviado ({arq.name})")
        achou = next((e for e in (".png", ".jpg", ".webp") if uploads._get(f"uploads/logo-{nome}{e}") is not None), None)
        if achou:
            sp.logo_path = f"/uploads/logo-{nome}{achou}"
            print(f"{sp.brand}: logo ligado ({sp.logo_path})")
        else:
            print(f"{sp.brand}: sem logo (coloque {nome}.png na pasta)")
    db.commit()
print("pronto")
