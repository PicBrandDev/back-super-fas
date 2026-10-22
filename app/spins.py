"""Giros da roleta (PicKap): cada giro tem um motivo e é gasto individualmente."""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .schemas import SpinCreditOut, br_date

WELCOME = "Bônus de boas-vindas"
RETRY = "Tente de novo: giro devolvido"


def _credits(db: Session, f: m.Fandom) -> list[m.SpinCredit]:
    q = select(m.SpinCredit).where(m.SpinCredit.artist_id == f.artist_id, m.SpinCredit.user_id == f.user_id)
    return list(db.scalars(q.order_by(m.SpinCredit.created_at)))


def sync(db: Session, f: m.Fandom) -> None:
    """`Fandom.spins` é sempre a quantidade de giros ainda não usados."""
    f.spins = sum(1 for c in _credits(db, f) if c.used_at is None)


def ensure_credits(db: Session, f: m.Fandom) -> list[m.SpinCredit]:
    """Na primeira vez, os giros que o fã já tinha viram giros de boas-vindas."""
    credits = _credits(db, f)
    if not credits and f.spins > 0:
        for _ in range(f.spins):
            db.add(m.SpinCredit(artist_id=f.artist_id, user_id=f.user_id, reason=WELCOME))
        db.flush()
        credits = _credits(db, f)
    return credits


def grant(db: Session, f: m.Fandom, reason: str) -> m.SpinCredit:
    ensure_credits(db, f)
    c = m.SpinCredit(artist_id=f.artist_id, user_id=f.user_id, reason=reason[:200])
    db.add(c)
    db.flush()
    sync(db, f)
    return c


def take(db: Session, f: m.Fandom, credit_id: str | None) -> m.SpinCredit:
    """Escolhe o giro que será gasto: o pedido, ou o mais antigo que ainda não foi usado."""
    credits = ensure_credits(db, f)
    if credit_id:
        c = next((c for c in credits if c.id == credit_id), None)
        if not c:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Giro não encontrado.")
        if c.used_at is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esse giro já foi usado.")
        return c
    c = next((c for c in credits if c.used_at is None), None)
    if not c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não tem giros disponíveis.")
    return c


def use(c: m.SpinCredit, prize_label: str) -> None:
    c.used_at = datetime.now(timezone.utc)
    c.prize_label = prize_label


def out(db: Session, f: m.Fandom) -> list[SpinCreditOut]:
    """Giros disponíveis primeiro (mais antigos primeiro), depois os usados (mais recentes primeiro)."""
    credits = ensure_credits(db, f)
    free = [c for c in credits if c.used_at is None]
    used = sorted((c for c in credits if c.used_at is not None), key=lambda c: c.used_at.replace(tzinfo=None), reverse=True)
    return [
        SpinCreditOut(id=c.id, reason=c.reason, used=c.used_at is not None, prize_label=c.prize_label or None, date=br_date(c.created_at.date()))
        for c in free + used
    ]
