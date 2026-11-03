"""Salva fotos enviadas pelo admin (Drop News, foto de perfil dos fã clubes) e artes dos patrocinadores.

Com UPLOADS_S3_BUCKET o arquivo vai para o bucket (chaves `uploads/<nome>`, miniaturas em `thumbs/<largura>/<nome>.jpg`);
sem ele, fica em UPLOAD_DIR. Em qualquer caso o caminho guardado no banco é o mesmo (`/uploads/<nome>`)."""

import io
import mimetypes
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .config import get_settings
from .models import new_id

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def use_bucket() -> bool:
    return bool(get_settings().uploads_s3_bucket)


@lru_cache
def _client():
    import boto3

    s = get_settings()
    kw: dict = {"region_name": s.uploads_aws_region}
    if s.uploads_aws_access_key_id and s.uploads_aws_secret_access_key:
        kw["aws_access_key_id"] = s.uploads_aws_access_key_id
        kw["aws_secret_access_key"] = s.uploads_aws_secret_access_key
    return boto3.client("s3", **kw)


def _get(key: str) -> bytes | None:
    from botocore.exceptions import ClientError

    try:
        return _client().get_object(Bucket=get_settings().uploads_s3_bucket, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def _put(key: str, data: bytes, content_type: str) -> None:
    _client().put_object(Bucket=get_settings().uploads_s3_bucket, Key=key, Body=data, ContentType=content_type)


def save_bytes(data: bytes, ext: str) -> str:
    """Grava o arquivo (bucket ou UPLOAD_DIR) e devolve o caminho público (ex.: /uploads/abc.jpg)."""
    name = f"{new_id()}{ext}"
    if use_bucket():
        _put(f"uploads/{name}", data, mimetypes.types_map.get(ext, "application/octet-stream"))
    else:
        folder = Path(get_settings().upload_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return f"/uploads/{name}"


def read_bytes(name: str) -> bytes | None:
    """Conteúdo de um arquivo enviado (bucket primeiro; se ainda não foi migrado, o disco). None se não existir."""
    name = Path(name).name
    if use_bucket():
        data = _get(f"uploads/{name}")
        if data is not None:
            return data
    path = Path(get_settings().upload_dir) / name
    return path.read_bytes() if path.is_file() else None


def make_thumb(data: bytes, width: int) -> bytes | None:
    """JPEG reduzido para `width` px de largura; None se a foto já é menor ou não deu para ler."""
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            if im.width <= width:
                return None
            im = im.convert("RGB")
            im.thumbnail((width, width * 4), Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, "JPEG", quality=80, optimize=True, progressive=True)
            return out.getvalue()
    except Exception:
        return None


def fetch(name: str, width: int | None = None) -> tuple[bytes, str] | None:
    """Entrega (bytes, tipo) direto do bucket; a miniatura é criada na primeira vez e guardada no próprio bucket.
    None se o arquivo não está no bucket (aí a rota cai no disco)."""
    if not use_bucket() or Path(name).name != name or name.startswith("."):
        return None
    if width:
        key = f"thumbs/{width}/{Path(name).stem}.jpg"
        cached = _get(key)
        if cached is not None:
            return cached, "image/jpeg"
    original = _get(f"uploads/{name}")
    if original is None:
        return None
    if width and Path(name).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        thumb = make_thumb(original, width)
        if thumb:
            _put(f"thumbs/{width}/{Path(name).stem}.jpg", thumb, "image/jpeg")
            return thumb, "image/jpeg"
    return original, mimetypes.guess_type(name)[0] or "application/octet-stream"


async def save_image(file: UploadFile | None) -> str:
    """Grava a foto enviada e devolve o caminho público (ex.: /uploads/abc.jpg). Sem arquivo, devolve vazio."""
    if not file or not file.filename:
        return ""
    ext = IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envie a foto em JPG, PNG ou WebP.")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A foto pode ter no máximo 5 MB.")
    return save_bytes(data, ext)
