"""Brindes que o fã ganha na roleta do PicKup (Meus brindes): cupom de desconto, ingresso de pista, retirada na lojinha."""

import secrets
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .schemas import RewardOut, br_date

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O e 1/I, para ler e digitar sem erro
VALID_DAYS = 90  # prazo para usar o cupom e retirar o brinde

INSTRUCTIONS = {
    "ticket": "Ingresso unitário de pista. Retire na bilheteria do próximo show com este código e um documento com foto.",
    "pickup": "Retire na lojinha do Vintage, no show, com este código e um documento com foto.",
    "": "Retire no próximo evento com este código e a sua identidade de fã.",
}


def _code(db: Session, artist_id: str, table: type, column) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        if not db.scalar(select(table.id).where(table.artist_id == artist_id, column == code)):
            return code


def create_for(db: Session, club: m.FanClub, user: m.User, prize: m.Prize) -> m.Reward | None:
    """Guarda o brinde que saiu na roleta (nada para "não foi dessa vez" e "tente de novo")."""
    if prize.is_retry or prize.kind in ("none", "retry"):
        return None
    expires = date.today() + timedelta(days=VALID_DAYS)
    coupon_code = ""
    if prize.kind == "coupon":
        while True:
            coupon_code = f"ROLETA{prize.percent or 10}-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if not db.scalar(select(m.Coupon.id).where(m.Coupon.artist_id == club.artist_id, m.Coupon.code == coupon_code)):
                break
        db.add(
            m.Coupon(
                artist_id=club.artist_id, user_id=user.id, code=coupon_code, kind="percent", value=prize.percent or 10,
                max_uses=1, expires_on=expires, source="Prêmio da roleta do PicKup",
            )
        )
        how = prize.instructions or f"Cupom de {prize.percent or 10}% no ingresso. Ele já está em Meus cupons: é só aplicar no carrinho da compra."
    else:
        how = prize.instructions or INSTRUCTIONS.get(prize.kind, INSTRUCTIONS[""])
    reward = m.Reward(
        artist_id=club.artist_id, club_id=club.id, user_id=user.id, label=prize.label, kind=prize.kind or "", prize_id=prize.id,
        code=_code(db, club.artist_id, m.Reward, m.Reward.code), instructions=how, coupon_code=coupon_code, expires_on=expires,
    )
    db.add(reward)
    db.flush()
    return reward


def status_of(db: Session, r: m.Reward) -> str:
    if r.kind == "coupon":
        c = db.scalar(select(m.Coupon).where(m.Coupon.artist_id == r.artist_id, m.Coupon.user_id == r.user_id, m.Coupon.code == r.coupon_code))
        if c and c.max_uses and c.used >= c.max_uses:
            return "used"
    elif r.redeemed_at:
        return "redeemed"
    return "expired" if r.expires_on and r.expires_on < date.today() else "available"


def out(db: Session, r: m.Reward) -> RewardOut:
    return RewardOut(
        id=r.id, label=r.label, kind=r.kind, code=r.code, instructions=r.instructions, coupon_code=r.coupon_code,
        status=status_of(db, r), expires_on=r.expires_on, won_at=br_date(r.created_at),
    )


def mine(db: Session, artist: m.Artist, user: m.User) -> list[m.Reward]:
    q = select(m.Reward).where(m.Reward.artist_id == artist.id, m.Reward.user_id == user.id).order_by(m.Reward.created_at.desc())
    return list(db.scalars(q))


def won_query(club: m.FanClub, prize: m.Prize):
    """Brindes que saíram desta fatia da roleta (os antigos, sem `prize_id`, são ligados pelo nome da fatia)."""
    return select(m.Reward).where(
        m.Reward.club_id == club.id,
        (m.Reward.prize_id == prize.id) | (m.Reward.prize_id.is_(None) & (m.Reward.label == prize.label)),
    )


def won(db: Session, club: m.FanClub, prize: m.Prize) -> int:
    return len(db.scalars(won_query(club, prize)).all())


def remaining(db: Session, club: m.FanClub, prize: m.Prize) -> int | None:
    """Quantas unidades ainda podem sair (None = ilimitado)."""
    return None if prize.stock is None else max(0, prize.stock - won(db, club, prize))
