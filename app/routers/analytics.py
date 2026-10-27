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


class ClubHighlight(Camel):
    """Os números que comparam os fã clubes entre si (últimos 30 dias, quando não diz o contrário)."""

    slug: str
    name: str
    city: str
    is_master: bool
    avatar: str | None = None
    # conteúdo: o que o fã clube já publicou
    posts: int
    posts_with_photo: int
    prizes: int
    content: int  # posts + fatias da roleta
    # feed: o que bombou nos posts dos últimos 30 dias
    posts_month: int
    likes: int
    comments: int
    reposts: int
    views: int
    buzz: int  # curtidas + 2 x comentários + 3 x republicações
    # gente
    members: int  # inscritos (total)
    new_members_month: int
    subscribers: int  # assinantes pagantes entre os inscritos
    active_members: int  # inscritos que postaram, comentaram ou compartilharam nos últimos 30 dias
    active_rate: int  # % dos inscritos que estiveram ativos


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


def _highlight(db, club: m.FanClub, since: date, paying: set[str]) -> ClubHighlight:
    posts = db.scalars(select(m.Post).where(m.Post.club_id == club.id)).all()
    recent = [p for p in posts if p.created_at.date() >= since]
    people = {mb.user_id for mb in club.members} | {st.user_id for st in club.staff}
    active = {p.author_id for p in recent if p.author_id in people}
    post_ids = [p.id for p in posts]
    if post_ids:
        active |= {
            c.author_id
            for c in db.scalars(select(m.PostComment).where(m.PostComment.post_id.in_(post_ids)))
            if c.author_id in people and c.created_at.date() >= since
        }
    active |= {
        sh.user_id
        for sh in db.scalars(select(m.InstagramShare).where(m.InstagramShare.artist_id == club.artist_id, m.InstagramShare.user_id.in_(people)))
        if sh.created_at.date() >= since
    } if people else set()
    members = len(club.members)
    n_active = len(active & {mb.user_id for mb in club.members}) if members else 0
    prizes = len(db.scalars(select(m.Prize.id).where(m.Prize.club_id == club.id)).all())
    likes, comments, reposts = (sum(getattr(p, f) for p in recent) for f in ("likes", "comments", "reposts"))
    return ClubHighlight(
        slug=club.slug,
        name=club.name,
        city=club.city,
        is_master=club.is_master,
        avatar=club.avatar_path or None,
        posts=len(posts),
        posts_with_photo=sum(1 for p in posts if p.image_path),
        prizes=prizes,
        content=len(posts) + prizes,
        posts_month=len(recent),
        likes=likes,
        comments=comments,
        reposts=reposts,
        views=sum(p.views for p in recent),
        buzz=likes + 2 * comments + 3 * reposts,
        members=members,
        new_members_month=sum(1 for mb in club.members if mb.created_at.date() >= since),
        subscribers=sum(1 for mb in club.members if mb.user_id in paying),
        active_members=n_active,
        active_rate=round(100 * n_active / members) if members else 0,
    )


@router.get("/artists/{slug}/clubs-highlights", response_model=list[ClubHighlight])
def clubs_highlights(artist: ManagedArtist, db: DB):
    """Compara os fã clubes ativos: quem tem mais conteúdo, quem bomba no feed, mais membros ativos e mais inscritos."""
    since = _today() - timedelta(days=DAYS - 1)
    paying = {f.user_id for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.member_status == "active"))}
    clubs = sorted((c for c in artist.clubs if c.status == "active"), key=lambda c: (not c.is_master, c.position, c.created_at))
    return [_highlight(db, c, since, paying) for c in clubs]


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


# ---------------------------------------------------------------- vitrines alugadas


class RentalOut(Camel):
    slot_key: str  # ex.: "home", "mural", "loja" ou "fa-clube-sp.home": diz em que tela a vitrine fica
    slot_name: str
    where: str  # onde a vitrine aparece (ex.: "Mural · topo")
    diagram_top: int = 20  # posição da vitrine no desenho do celular (mesmos valores de quando o patrocinador aluga)
    diagram_height: int = 16
    fan_club: str | None = None  # fã clube dono da vitrine (vazio = vitrine do ambiente)
    sponsor: str
    title: str
    start: date | None = None
    end: date | None = None
    days: int | None = None  # duração do aluguel em dias (None quando falta uma das datas)
    status: str  # live | scheduled | ended
    price_cents_per_week: int | None = None  # preço da vitrine por semana
    estimated_total_cents: int | None = None  # semanas (arredondadas para cima) x preço, quando há as duas informações


@router.get("/artists/{slug}/rentals", response_model=list[RentalOut])
def rentals(artist: ManagedArtist, db: DB):
    """Todas as vitrines alugadas do ambiente e dos fã clubes: quem alugou, por quanto tempo e qual vitrine."""
    today = date.today()
    q = (
        select(m.Campaign)
        .join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id)
        .where(m.AdSlot.artist_id == artist.id, m.Campaign.status == "approved")
    )
    out: list[RentalOut] = []
    for c in db.scalars(q):
        days = (c.end - c.start).days + 1 if c.start and c.end else None
        if c.end and c.end < today:
            status = "ended"
        elif c.start and c.start > today:
            status = "scheduled"
        else:
            status = "live"
        price = c.slot.price_cents
        out.append(
            RentalOut(
                slot_key=c.slot.key,
                slot_name=c.slot.name,
                where=c.slot.where,
                diagram_top=c.slot.diagram_top,
                diagram_height=c.slot.diagram_height,
                fan_club=c.slot.club.name if c.slot.club else None,
                sponsor=c.brand or c.sponsor.brand or c.sponsor.email,
                title=c.title,
                start=c.start,
                end=c.end,
                days=days,
                status=status,
                price_cents_per_week=price,
                estimated_total_cents=(-(-days // 7)) * price if days and price else None,
            )
        )
    def key(r: RentalOut) -> tuple[int, int]:
        # No ar: as que terminam primeiro; agendadas: as que começam primeiro; encerradas: as mais recentes.
        if r.status == "ended":
            return (2, -(r.end.toordinal() if r.end else 0))
        if r.status == "scheduled":
            return (1, (r.start or date.max).toordinal())
        return (0, (r.end or date.max).toordinal())

    out.sort(key=key)
    return out
