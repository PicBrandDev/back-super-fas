"""Resumo de confiança do vendedor mostrado ao comprador: só dados públicos e seguros, calculados em lote (sem N+1)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import br_date
from . import identity
from .base import O_COMPLETED
from .models import Order, Review, UserIdentity
from .schemas import ClubPositionOut, ReviewOut, SellerOut

_RANK = {"owner": 0, "helper": 1, "member": 2}


def public_handle(u: m.User) -> str:
    """O handle escolhido; nunca o prefixo do e-mail. Sem handle: 'Fã' e o fim do id."""
    return (u.handle or "").strip() or f"Fã {u.id[-4:]}"


def short_name(u: m.User) -> str:
    """Primeiro nome e inicial do sobrenome (ex.: 'Julia C.')."""
    parts = (u.name or "").split()
    if not parts:
        return public_handle(u)
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def sellers(db: Session, artist: m.Artist, ids: list[str]) -> dict[str, SellerOut]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_(ids)))}
    sales = dict(db.execute(select(Order.seller_id, func.count(Order.id)).where(Order.seller_id.in_(ids), Order.status == O_COMPLETED).group_by(Order.seller_id)).all())
    ratings = {
        sid: (avg, n)
        for sid, avg, n in db.execute(
            select(Review.seller_id, func.avg(Review.rating), func.count(Review.id)).where(Review.seller_id.in_(ids), Review.hidden.is_(False)).group_by(Review.seller_id)
        ).all()
    }
    idents = {i.user_id: i.level for i in db.scalars(select(UserIdentity).where(UserIdentity.user_id.in_(ids)))}
    fandoms = {f.user_id: f for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id.in_(ids)))}
    clubs: dict[str, dict[str, ClubPositionOut]] = {i: {} for i in ids}
    rows = db.execute(
        select(m.ClubMember.user_id, m.FanClub).join(m.FanClub, m.FanClub.id == m.ClubMember.club_id).where(m.FanClub.artist_id == artist.id, m.ClubMember.user_id.in_(ids))
    ).all()
    for uid, c in rows:
        clubs[uid][c.id] = ClubPositionOut(name=c.name, slug=c.slug, position="member")
    staff = db.execute(
        select(m.ClubStaff.user_id, m.ClubStaff.role, m.FanClub).join(m.FanClub, m.FanClub.id == m.ClubStaff.club_id).where(m.FanClub.artist_id == artist.id, m.ClubStaff.user_id.in_(ids))
    ).all()
    for uid, role, c in staff:
        cur = clubs[uid].get(c.id)
        if not cur or _RANK[role] < _RANK[cur.position]:
            clubs[uid][c.id] = ClubPositionOut(name=c.name, slug=c.slug, position=role)

    out: dict[str, SellerOut] = {}
    for uid in ids:
        u = users.get(uid)
        if not u:
            continue
        avg, n = ratings.get(uid, (None, 0))
        f = fandoms.get(uid)
        level = idents.get(uid, "")
        out[uid] = SellerOut(
            user_id=uid, handle=public_handle(u), display_name=short_name(u), avatar=u.avatar_path or None, member_since=br_date(u.created_at.date()),
            completed_sales=sales.get(uid, 0), avg_rating=round(float(avg), 2) if avg is not None else None, rating_count=n,
            clubs=sorted(clubs[uid].values(), key=lambda c: (_RANK[c.position], c.name)), is_member=bool(f and f.member_status == "active"),
            identity_level=level or "none", identity_verified=level == "verified",
        )
    return out


def reviews(db: Session, seller_id: str, page: int = 1, size: int = 20) -> list[ReviewOut]:
    q = select(Review).where(Review.seller_id == seller_id, Review.hidden.is_(False)).order_by(Review.created_at.desc()).offset(max(page - 1, 0) * size).limit(size)
    out = []
    for r in db.scalars(q):
        buyer = db.get(m.User, r.buyer_id)
        out.append(ReviewOut(id=r.id, rating=r.rating, comment=r.comment, created_at=br_date(r.created_at.date()), buyer_name=short_name(buyer) if buyer else "Fã"))
    return out
