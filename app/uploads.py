"""Salva fotos enviadas pelo admin (Drop News, foto de perfil dos fã clubes)."""

from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .config import get_settings
from .models import new_id

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


async def save_image(file: UploadFile | None) -> str:
    """Grava a foto em UPLOAD_DIR e devolve o caminho público (ex.: /uploads/abc.jpg). Sem arquivo, devolve vazio."""
    if not file or not file.filename:
        return ""
    ext = IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envie a foto em JPG, PNG ou WebP.")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A foto pode ter no máximo 5 MB.")
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{new_id()}{ext}"
    (folder / name).write_bytes(data)
    return f"/uploads/{name}"
