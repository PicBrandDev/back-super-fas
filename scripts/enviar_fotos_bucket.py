"""Envia para o bucket as fotos que estão na pasta de uploads (não apaga nada e pula o que já está lá).

Rode no servidor depois de definir UPLOADS_S3_BUCKET e as chaves no .env:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/enviar_fotos_bucket.py
Local: PYTHONPATH=. python scripts/enviar_fotos_bucket.py
"""

import mimetypes
from pathlib import Path

from app import uploads
from app.config import get_settings

cfg = get_settings()
if not uploads.use_bucket():
    raise SystemExit("Defina UPLOADS_S3_BUCKET (e as chaves UPLOADS_AWS_*) antes de rodar.")

folder = Path(cfg.upload_dir)
sent = skipped = 0
for path in sorted(folder.iterdir()) if folder.is_dir() else []:
    if not path.is_file() or path.name.startswith("."):
        continue
    key = f"uploads/{path.name}"
    if uploads._get(key) is not None:
        skipped += 1
        continue
    uploads._put(key, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    sent += 1
    print("enviada:", path.name)
print(f"{sent} enviadas, {skipped} já estavam no bucket.")
