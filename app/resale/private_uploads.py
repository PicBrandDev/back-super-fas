"""Prova do ingresso: arquivo em pasta PRIVADA (fora do /uploads público), validado pelo conteúdo e servido só ao vendedor e ao admin."""

import hashlib
from pathlib import Path

from fastapi import UploadFile

from ..config import get_settings
from ..models import new_id
from .base import PROOF_MAX_BYTES, ResaleError

# assinatura (magic bytes) -> (tipo, extensão). Não confiamos no Content-Type enviado pelo navegador.
_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"%PDF-", "application/pdf", ".pdf"),
]


def private_dir() -> Path:
    s = get_settings()
    folder = Path(s.private_upload_dir) if s.private_upload_dir else Path(s.upload_dir).resolve().parent / "private"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def sniff(data: bytes) -> tuple[str, str] | None:
    for sig, mime, ext in _SIGNATURES:
        if data.startswith(sig):
            return mime, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


async def save_proof(file: UploadFile | None) -> tuple[str, str, str]:
    """Grava a prova e devolve (nome do arquivo, mime, sha256). Aceita JPG, PNG, WebP e PDF de até 8 MB."""
    if not file or not file.filename:
        raise ResaleError("PROOF_REQUIRED", "Envie a prova do ingresso (foto, print ou PDF).")
    data = await file.read(PROOF_MAX_BYTES + 1)
    if len(data) > PROOF_MAX_BYTES:
        raise ResaleError("PROOF_TOO_BIG", "A prova pode ter no máximo 8 MB.")
    kind = sniff(data)
    if not kind:
        raise ResaleError("PROOF_TYPE", "Envie a prova em JPG, PNG, WebP ou PDF.")
    mime, ext = kind
    name = f"{new_id()}{ext}"
    (private_dir() / name).write_bytes(data)
    return name, mime, hashlib.sha256(data).hexdigest()


def proof_path(name: str) -> Path:
    """Caminho do arquivo; recusa nomes com pasta (path traversal)."""
    p = (private_dir() / Path(name).name).resolve()
    if p.parent != private_dir().resolve() or not p.is_file():
        raise ResaleError("NOT_FOUND", "Arquivo não encontrado.", 404)
    return p
