"""Cupons de desconto na compra do ingresso (percentual ou valor fixo, gerais ou pessoais)."""

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings

ROULETTE_CODE = "ROLETA10"


def label(c: m.Coupon) -> str:
    if c.kind == "percent":
        return f"{c.value}% de desconto"
    return f"R$ {c.value / 100:.2f}".replace(".", ",") + " de desconto"


def usable(c: m.Coupon) -> bool:
    return c.active and (c.expires_on is None or c.expires_on >= date.today()) and (c.max_uses == 0 or c.used < c.max_uses)


def mine(db: Session, artist: m.Artist, user: m.User) -> list[m.Coupon]:
    """Cupons pessoais do fã que ainda valem (os gerais ele digita)."""
    q = select(m.Coupon).where(m.Coupon.artist_id == artist.id, m.Coupon.user_id == user.id).order_by(m.Coupon.code)
    return [c for c in db.scalars(q) if usable(c)]


def find(db: Session, artist: m.Artist, user: m.User, code: str) -> m.Coupon:
    """O cupom que vale para este fã (o pessoal tem prioridade sobre o geral) ou 400 em português."""
    code = code.strip().upper()
    q = select(m.Coupon).where(
        m.Coupon.artist_id == artist.id, m.Coupon.code == code, or_(m.Coupon.user_id.is_(None), m.Coupon.user_id == user.id)
    )
    found = sorted(db.scalars(q), key=lambda c: c.user_id is None)  # pessoais primeiro
    c = next((c for c in found if usable(c)), None)
    if not c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cupom inválido, expirado ou já utilizado.")
    return c


def discount(c: m.Coupon, subtotal_cents: int) -> int:
    off = subtotal_cents * min(c.value, 100) // 100 if c.kind == "percent" else c.value
    return max(0, min(off, subtotal_cents))


def ensure_roulette_coupon(db: Session, artist: m.Artist, user: m.User) -> None:
    """Demonstração: todo fã tem o cupom de 10% que "ganhou na roleta" (uso único). Só com DEMO_PHOTO_TICKET ligado."""
    if not get_settings().demo_photo_ticket or user.role not in (m.ROLE_FAN, m.ROLE_ARTIST_ADMIN):
        return
    if db.scalar(select(m.Coupon.id).where(m.Coupon.artist_id == artist.id, m.Coupon.user_id == user.id, m.Coupon.code == ROULETTE_CODE)):
        return
    db.add(m.Coupon(artist_id=artist.id, user_id=user.id, code=ROULETTE_CODE, kind="percent", value=10, max_uses=1, source="Prêmio da roleta do PicKup"))
    db.commit()
