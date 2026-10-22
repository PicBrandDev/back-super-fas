"""Confere no Instagram os posts dos fãs com a hashtag do ranking "Fã Super" (API Graph da Meta).

Como funciona: a legenda sugerida pelo app leva a hashtag e um código do fã (ex.: `FS-7K2QM`). A API de busca por
hashtag devolve os posts públicos mais recentes (últimas 24 horas) e, por privacidade, não diz quem postou:
quem identifica o fã é o código na legenda. Cada post do Instagram pontua uma vez só (`media_id` único).
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings

log = logging.getLogger("superfas.instagram")

CODE_RE = re.compile(r"\bFS-[A-Z2-9]{5}\b", re.IGNORECASE)
MAX_PAGES = 5


@dataclass
class SyncResult:
    enabled: bool
    found: int = 0  # posts da hashtag lidos
    verified: int = 0  # compartilhamentos novos que pontuaram
    error: str | None = None


def enabled() -> bool:
    s = get_settings()
    return bool(s.instagram_enabled and s.instagram_user_id and s.instagram_access_token)


def _get(path: str, params: dict) -> dict:
    s = get_settings()
    q = urllib.parse.urlencode({**params, "access_token": s.instagram_access_token})
    url = f"https://graph.facebook.com/{s.graph_api_version}/{path}?{q}"
    with urllib.request.urlopen(url, timeout=20) as res:  # noqa: S310 - URL fixa da Meta
        return json.loads(res.read().decode())


def recent_media() -> list[dict]:
    """Posts públicos recentes (24 h) com a hashtag: id, legenda e link."""
    s = get_settings()
    tag = _get("ig_hashtag_search", {"user_id": s.instagram_user_id, "q": s.instagram_hashtag})["data"][0]["id"]
    items: list[dict] = []
    page = _get(f"{tag}/recent_media", {"user_id": s.instagram_user_id, "fields": "id,caption,permalink,timestamp", "limit": 50})
    for _ in range(MAX_PAGES):
        items += page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            break
        with urllib.request.urlopen(nxt, timeout=20) as res:  # noqa: S310 - URL devolvida pela Meta
            page = json.loads(res.read().decode())
    return items


def share_code(db: Session, f: m.Fandom) -> str:
    """Código do fã nas legendas (criado na primeira vez e único no ambiente)."""
    import secrets

    if f.share_code:
        return f.share_code
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "FS-" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not db.scalar(select(m.Fandom).where(m.Fandom.share_code == code)):
            f.share_code = code
            return code


def caption_for(text: str, code: str) -> str:
    """Legenda sugerida: o texto do post + a hashtag do ranking + o código do fã."""
    tag = get_settings().instagram_hashtag
    return f"{text.strip()[:280]}\n\n#{tag} {code}"


def sync(db: Session, artist: m.Artist, media: list[dict] | None = None) -> SyncResult:
    """Lê os posts da hashtag e dá ponto aos fãs cujo código aparece na legenda. `media` serve para testes."""
    if media is None:
        if not enabled():
            return SyncResult(enabled=False)
        try:
            media = recent_media()
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao consultar a API do Instagram")
            return SyncResult(enabled=True, error=str(exc)[:200])
    tag = get_settings().instagram_hashtag.lower()
    codes = {f.share_code.upper(): f for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.share_code != ""))}
    out = SyncResult(enabled=True, found=len(media))
    for item in media:
        caption = item.get("caption") or ""
        if f"#{tag}" not in caption.lower():
            continue
        match = CODE_RE.search(caption)
        fandom = codes.get(match.group(0).upper()) if match else None
        media_id = item.get("id")
        if not fandom or not media_id or db.scalar(select(m.InstagramShare).where(m.InstagramShare.media_id == media_id)):
            continue
        # Usa o compartilhamento "iniciado" mais antigo do fã, se houver; senão cria um verificado.
        share = db.scalar(
            select(m.InstagramShare)
            .where(m.InstagramShare.artist_id == artist.id, m.InstagramShare.user_id == fandom.user_id, m.InstagramShare.status == "started")
            .order_by(m.InstagramShare.created_at)
        ) or m.InstagramShare(artist_id=artist.id, user_id=fandom.user_id)
        share.status = "verified"
        share.media_id = media_id
        share.permalink = item.get("permalink") or ""
        share.verified_at = datetime.now(timezone.utc)
        db.add(share)
        out.verified += 1
    db.commit()
    return out
