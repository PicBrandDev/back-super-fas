"""Painel dos fã clubes do ambiente e analytics de cada um (só leitura).

O painel é do admin do ambiente (equipe do fã clube master ou admin da plataforma);
o analytics de um fã clube também abre para a equipe daquele fã clube.
"""

from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter
from sqlalchemy import select

from .. import models as m
from ..schemas import Camel
from ..security import DB, ManagedArtist, ManagedClub

router = APIRouter(tags=["Analytics"])

DAYS = 30


class ClubOverview(Camel):
    id: str
    slug: str
    name: str
    city: str
    is_master: bool
    status: str
    avatar: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    members: int
    new_members_month: int
    posts: int
    posts_month: int
    staff: int


class DayPoint(Camel):
    day: str  # AAAA-MM-DD
    new_members: int
    posts: int


class CityCount(Camel):
    city: str
    members: int


class TopPost(Camel):
    id: str
    text: str
    author: str
    likes: int
    comments: int
    reposts: int


class ClubAnalytics(Camel):
    club: ClubOverview
    subscribers: int
    likes: int
    comments: int
    reposts: int
    new_members_prev_month: int
    active_slots: int
    approved_campaigns: int
    series: list[DayPoint]
    top_cities: list[CityCount]
    top_posts: list[TopPost]
    staff_names: list[str]


def _today() -> date:
    return date.today()


def _overview(db, club: m.FanClub, since: date) -> ClubOverview:
    owner = next((st.user for st in club.staff if st.role == m.STAFF_OWNER), None)
    posts = db.scalars(select(m.Post).where(m.Post.club_id == club.id)).all()
    return ClubOverview(
        id=club.id,
        slug=club.slug,
        name=club.name,
        city=club.city,
        is_master=club.is_master,
        status=club.status,
        avatar=club.avatar_path or None,
        owner_name=owner.name if owner else None,
        owner_email=owner.email if owner else None,
        members=len(club.members),
        new_members_month=sum(1 for mb in club.members if mb.created_at.date() >= since),
        posts=len(posts),
        posts_month=sum(1 for p in posts if p.created_at.date() >= since),
        staff=len(club.staff),
    )


@router.get("/artists/{slug}/clubs-overview", response_model=list[ClubOverview])
def clubs_overview(artist: ManagedArtist, db: DB):
    """Todos os fã clubes do ambiente, com o dono e os números dos últimos 30 dias."""
    since = _today() - timedelta(days=DAYS - 1)
    clubs = sorted(artist.clubs, key=lambda c: (not c.is_master, c.position, c.created_at))
    return [_overview(db, c, since) for c in clubs]


@router.get("/artists/{slug}/clubs/{club}/analytics", response_model=ClubAnalytics)
def club_analytics(club: ManagedClub, db: DB):
    today = _today()
    since = today - timedelta(days=DAYS - 1)
    prev_since = since - timedelta(days=DAYS)

    posts = db.scalars(select(m.Post).where(m.Post.club_id == club.id)).all()
    new_by_day = Counter(mb.created_at.date() for mb in club.members if mb.created_at.date() >= since)
    posts_by_day = Counter(p.created_at.date() for p in posts if p.created_at.date() >= since)
    series = [
        DayPoint(day=(d := since + timedelta(days=i)).isoformat(), new_members=new_by_day[d], posts=posts_by_day[d])
        for i in range(DAYS)
    ]

    subscribers = {
        f.user_id
        for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == club.artist_id, m.Fandom.member_status == "active"))
    }
    cities = Counter((mb.user.city or "").strip() or "Não informada" for mb in club.members)
    top_posts = sorted(posts, key=lambda p: (p.likes, p.created_at), reverse=True)[:5]

    slot_ids = [s.id for s in db.scalars(select(m.AdSlot).where(m.AdSlot.club_id == club.id))]
    active_slots = sum(1 for s in db.scalars(select(m.AdSlot).where(m.AdSlot.club_id == club.id)) if s.active)
    approved = (
        len(db.scalars(select(m.Campaign).where(m.Campaign.slot_id.in_(slot_ids), m.Campaign.status == "approved")).all())
        if slot_ids
        else 0
    )

    return ClubAnalytics(
        club=_overview(db, club, since),
        subscribers=sum(1 for mb in club.members if mb.user_id in subscribers),
        likes=sum(p.likes for p in posts),
        comments=sum(p.comments for p in posts),
        reposts=sum(p.reposts for p in posts),
        new_members_prev_month=sum(1 for mb in club.members if prev_since <= mb.created_at.date() < since),
        active_slots=active_slots,
        approved_campaigns=approved,
        series=series,
        top_cities=[CityCount(city=c, members=n) for c, n in cities.most_common(5)],
        top_posts=[
            TopPost(
                id=p.id,
                text=p.text[:140],
                author=p.author.name if p.author else ("Oficial" if p.official else "—"),
                likes=p.likes,
                comments=p.comments,
                reposts=p.reposts,
            )
            for p in top_posts
        ],
        staff_names=[st.user.name for st in club.staff],
    )


# ---------------------------------------------------------------- assinantes do ambiente


class PlaceCount(Camel):
    place: str
    subscribers: int


class SubscribersAnalytics(Camel):
    fans: int  # fãs do ambiente (com ou sem assinatura)
    active: int
    pending: int
    canceled: int
    new_subscribers_month: int  # assinaturas iniciadas nos últimos 30 dias
    monthly_revenue_cents: int  # assinantes ativos x preço do membro
    with_address: int  # assinantes ativos com UF informada
    series: list[dict]  # [{day, newSubscribers}] dos últimos 30 dias
    by_state: list[PlaceCount]
    by_city: list[PlaceCount]


@router.get("/artists/{slug}/subscribers-analytics", response_model=SubscribersAnalytics)
def subscribers_analytics(artist: ManagedArtist, db: DB):
    """Quantos assinantes o ambiente tem e de onde são (sem listar pessoas)."""
    since = _today() - timedelta(days=DAYS - 1)
    fandoms = db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id)).all()
    subs = [f for f in fandoms if f.member_status is not None]
    active = [f for f in subs if f.member_status == "active"]
    started = Counter(f.member_since for f in subs if f.member_since and f.member_since >= since)
    by_state = Counter((f.user.state or "").strip().upper() or "Não informado" for f in active)
    by_city = Counter(
        (f"{f.user.city.strip()}/{f.user.state.strip().upper()}" if f.user.city.strip() and f.user.state.strip() else f.user.city.strip())
        or "Não informada"
        for f in active
    )
    return SubscribersAnalytics(
        fans=len(fandoms),
        active=len(active),
        pending=sum(1 for f in subs if f.member_status == "pending"),
        canceled=sum(1 for f in subs if f.member_status == "canceled"),
        new_subscribers_month=sum(started.values()),
        monthly_revenue_cents=len(active) * artist.member_price_cents,
        with_address=sum(1 for f in active if f.user.state.strip()),
        series=[
            {"day": (d := since + timedelta(days=i)).isoformat(), "newSubscribers": started[d]} for i in range(DAYS)
        ],
        by_state=[PlaceCount(place=k, subscribers=n) for k, n in by_state.most_common()],
        by_city=[PlaceCount(place=k, subscribers=n) for k, n in by_city.most_common(10)],
    )
