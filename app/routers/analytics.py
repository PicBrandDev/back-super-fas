"""Painel dos fã clubes do ambiente e analytics de cada um (só leitura).

O painel é do admin do ambiente (equipe do fã clube master ou admin da plataforma);
o analytics de um fã clube também abre para a equipe daquele fã clube.
"""

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from .. import models as m
from ..schemas import Camel
from .ad_stats import sponsor_avatar
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
    owner_avatar: str | None = None
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
    image: str | None = None
    likes: int
    comments: int
    reposts: int


class OwnerCard(Camel):
    """Perfil do dono do fã clube (card da página de analytics)."""

    user_id: str
    name: str
    handle: str = ""
    email: str
    avatar: str | None = None
    city: str = ""
    state: str = ""
    role_label: str = ""
    since: date  # dono desde
    posts: int  # posts dele no fã clube
    shares: int  # compartilhamentos confirmados no Instagram
    points: float  # pontos no ranking
    position: int | None = None  # posição no ranking do fã clube
    ranked: int = 0  # quantas pessoas pontuam neste fã clube


class ClubAnalytics(Camel):
    club: ClubOverview
    owner: OwnerCard | None = None
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
        owner_avatar=(owner.avatar_path or None) if owner else None,
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


def _owner_card(db, club: m.FanClub, posts: list[m.Post]) -> OwnerCard | None:
    from .ranking import _board, home_members

    st = next((st for st in club.staff if st.role == m.STAFF_OWNER), None)
    if not st:
        return None
    u = st.user
    people = home_members(club.artist).get(club.id, set())
    rows = [r for r in _board(db, club.artist) if r[0] in people]
    idx = next((i for i, r in enumerate(rows) if r[0] == u.id), None)
    return OwnerCard(
        user_id=u.id,
        name=u.name,
        handle=u.handle or "",
        email=u.email,
        avatar=u.avatar_path or None,
        city=u.city,
        state=u.state,
        role_label=st.role_label,
        since=st.created_at.date(),
        posts=sum(1 for p in posts if p.author_id == u.id),
        shares=rows[idx][1] if idx is not None else 0,
        points=rows[idx][3] if idx is not None else 0.0,
        position=idx + 1 if idx is not None else None,
        ranked=len(rows),
    )


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
        owner=_owner_card(db, club, posts),
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
                image=p.image_path or None,
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
    price_cents: int = 0  # preço da assinatura por mês
    annual_revenue_cents: int = 0  # receita mensal x 12 (projeção)
    new_revenue_month_cents: int = 0  # assinaturas novas dos últimos 30 dias x preço
    pending_revenue_cents: int = 0  # o que entra se os pendentes confirmarem
    lost_revenue_cents: int = 0  # o que os cancelados deixaram de pagar por mês
    monthly_series: list[dict] = []  # [{month, label, subscribers, revenueCents}] dos últimos 6 meses


def _month_ends(today: date, n: int) -> list[date]:
    """Último dia de cada um dos n meses até o atual (o atual termina hoje)."""
    out, y, mo = [], today.year, today.month
    for _ in range(n):
        nxt = date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1)
        out.append(min(nxt - timedelta(days=1), today))
        mo -= 1
        if mo == 0:
            y, mo = y - 1, 12
    return out[::-1]


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


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
        price_cents=artist.member_price_cents,
        annual_revenue_cents=len(active) * artist.member_price_cents * 12,
        new_revenue_month_cents=sum(started.values()) * artist.member_price_cents,
        pending_revenue_cents=sum(1 for f in subs if f.member_status == "pending") * artist.member_price_cents,
        lost_revenue_cents=sum(1 for f in subs if f.member_status == "canceled") * artist.member_price_cents,
        # Estimativa pelas datas de assinatura: quem está ativo hoje e já tinha assinado até o fim de cada mês.
        monthly_series=[
            {
                "month": d.strftime("%Y-%m"),
                "label": f"{MESES[d.month - 1]}/{str(d.year)[2:]}",
                "subscribers": (n := sum(1 for f in active if f.member_since and f.member_since <= d)),
                "revenueCents": n * artist.member_price_cents,
            }
            for d in _month_ends(_today(), 6)
        ],
    )


# ---------------------------------------------------------------- lista de assinantes

PAGE_SIZE = 10


class SubscriberRow(Camel):
    user_id: str
    name: str
    handle: str = ""
    email: str
    avatar: str | None = None
    city: str = ""
    state: str = ""
    status: str  # active | pending | canceled
    since: date | None = None  # assinou em
    payment: str = ""
    luck_points: int = 0
    spins_left: int = 0


class SubscriberPage(Camel):
    total: int
    page: int
    pages: int
    page_size: int = PAGE_SIZE
    items: list[SubscriberRow]


def _spins_left(db, artist: m.Artist, user_ids: list[str]) -> dict[str, int]:
    rows = db.execute(
        select(m.SpinCredit.user_id, func.count(m.SpinCredit.id))
        .where(m.SpinCredit.artist_id == artist.id, m.SpinCredit.user_id.in_(user_ids), m.SpinCredit.used_at.is_(None))
        .group_by(m.SpinCredit.user_id)
    )
    return dict(rows.all())


@router.get("/artists/{slug}/subscribers", response_model=SubscriberPage)
def subscribers_list(artist: ManagedArtist, db: DB, q: str = "", page: int = 1):
    """Assinantes ativos, do que assinou por último para o mais antigo, de 10 em 10. `q` busca por nome, @ ou e-mail."""
    base = (
        select(m.Fandom, m.User)
        .join(m.User, m.User.id == m.Fandom.user_id)
        .where(m.Fandom.artist_id == artist.id, m.Fandom.member_status == "active")
    )
    term = q.strip().lower()
    if term:
        like = f"%{term}%"
        base = base.where(func.lower(m.User.name).like(like) | func.lower(m.User.handle).like(like) | func.lower(m.User.email).like(like))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(1, page), pages)
    rows = db.execute(
        base.order_by(m.Fandom.member_since.desc().nulls_last(), m.Fandom.created_at.desc()).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)
    ).all()
    left = _spins_left(db, artist, [u.id for _, u in rows]) if rows else {}
    return SubscriberPage(
        total=total,
        page=page,
        pages=pages,
        items=[
            SubscriberRow(
                user_id=u.id,
                name=u.name,
                handle=u.handle or "",
                email=u.email,
                avatar=u.avatar_path or None,
                city=u.city,
                state=u.state,
                status=f.member_status or "",
                since=f.member_since,
                payment=f.payment,
                luck_points=f.luck_points,
                spins_left=left.get(u.id, 0),
            )
            for f, u in rows
        ],
    )


class ActivityCoupon(Camel):
    code: str
    source: str
    kind: str  # percent | fixed
    value: int
    used: bool
    expires_on: date | None = None


class ActivityEvent(Camel):
    at: datetime
    kind: str  # assinou | giro | giro_ganho | brinde | retirada | cupom | ingresso | loja | share | confirmado | post | comentario
    title: str
    detail: str = ""


class ActivitySummary(Camel):
    spins_used: int
    spins_left: int
    luck_points: int
    rewards: int
    rewards_redeemed: int
    coupons: int
    coupons_used: int
    purchases: int
    spent_cents: int
    shares_confirmed: int
    posts: int
    comments: int


class SubscriberActivity(Camel):
    profile: SubscriberRow
    summary: ActivitySummary
    coupons: list[ActivityCoupon]
    events: list[ActivityEvent]  # as 80 ações mais recentes


def _at(d: date | datetime | None) -> datetime | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc)


def _brl(cents: int) -> str:
    return f"R$ {cents / 100:.2f}".replace(".", ",")


@router.get("/artists/{slug}/subscribers/{user_id}/activity", response_model=SubscriberActivity)
def subscriber_activity(user_id: str, artist: ManagedArtist, db: DB):
    """Ações de um assinante: roleta, brindes, cupons, compras, compartilhamentos, posts e comentários."""
    fandom = db.scalar(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == user_id))
    if not fandom or fandom.member_status is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assinante não encontrado.")
    u = fandom.user
    ev: list[ActivityEvent] = []

    def add(at, kind: str, title: str, detail: str = "") -> None:
        when = _at(at)
        if when:
            ev.append(ActivityEvent(at=when, kind=kind, title=title, detail=detail))

    add(fandom.member_since, "assinou", "Virou assinante", f"Pagamento: {fandom.payment}")
    credits = db.scalars(select(m.SpinCredit).where(m.SpinCredit.artist_id == artist.id, m.SpinCredit.user_id == u.id)).all()
    for c in credits:
        add(c.created_at, "giro_ganho", "Ganhou um giro da roleta", c.reason)
        if c.used_at:
            add(c.used_at, "giro", "Girou a roleta", f"Saiu: {c.prize_label}" if c.prize_label else "")
    rewards = db.scalars(select(m.Reward).where(m.Reward.artist_id == artist.id, m.Reward.user_id == u.id)).all()
    for r in rewards:
        add(r.created_at, "brinde", f"Ganhou o brinde {r.label}", f"Código {r.code}")
        if r.redeemed_at:
            add(r.redeemed_at, "retirada", f"Retirou o brinde {r.label}", f"Código {r.code}")
    tickets = db.scalars(select(m.TicketPurchase).where(m.TicketPurchase.artist_id == artist.id, m.TicketPurchase.user_id == u.id)).all()
    for t in tickets:
        add(t.created_at, "ingresso", f"Comprou {t.label}", _brl(t.price_cents))
        if t.coupon_code:
            add(t.created_at, "cupom", f"Usou o cupom {t.coupon_code}", f"Desconto de {_brl(t.discount_cents)}")
    products = db.scalars(select(m.ProductPurchase).where(m.ProductPurchase.artist_id == artist.id, m.ProductPurchase.user_id == u.id)).all()
    for p in products:
        add(p.created_at, "loja", f"Comprou na loja: {p.name}" + (f" x{p.qty}" if p.qty > 1 else ""), _brl(p.price_cents * p.qty))
    shares = db.scalars(select(m.InstagramShare).where(m.InstagramShare.artist_id == artist.id, m.InstagramShare.user_id == u.id)).all()
    for sh in shares:
        add(sh.created_at, "share", "Compartilhou com a hashtag", "" if sh.status == "verified" else "Aguardando conferência")
        if sh.verified_at:
            add(sh.verified_at, "confirmado", "Hashtag confirmada no Instagram", "+1 compartilhamento no ranking")
    club_ids = [c.id for c in artist.clubs]
    posts = db.scalars(select(m.Post).where(m.Post.author_id == u.id, (m.Post.artist_id == artist.id) | (m.Post.club_id.in_(club_ids)))).all()
    for p in posts:
        add(p.created_at, "post", "Publicou um post", p.text[:120])
    comments = db.scalars(
        select(m.PostComment).join(m.Post, m.Post.id == m.PostComment.post_id).where(m.PostComment.author_id == u.id, m.Post.artist_id == artist.id)
    ).all()
    for c in comments:
        add(c.created_at, "comentario", "Comentou num post", c.text[:120])

    coupon_rows = [
        ActivityCoupon(
            code=c.code,
            source=c.source,
            kind=c.kind,
            value=c.value,
            used=c.used > 0 or any(t.coupon_code == c.code for t in tickets),
            expires_on=c.expires_on,
        )
        for c in db.scalars(select(m.Coupon).where(m.Coupon.artist_id == artist.id, m.Coupon.user_id == u.id))
    ]
    ev.sort(key=lambda e: e.at, reverse=True)
    spins_left = sum(1 for c in credits if c.used_at is None)
    profile = SubscriberRow(
        user_id=u.id,
        name=u.name,
        handle=u.handle or "",
        email=u.email,
        avatar=u.avatar_path or None,
        city=u.city,
        state=u.state,
        status=fandom.member_status or "",
        since=fandom.member_since,
        payment=fandom.payment,
        luck_points=fandom.luck_points,
        spins_left=spins_left,
    )
    return SubscriberActivity(
        profile=profile,
        summary=ActivitySummary(
            spins_used=sum(1 for c in credits if c.used_at),
            spins_left=spins_left,
            luck_points=fandom.luck_points,
            rewards=len(rewards),
            rewards_redeemed=sum(1 for r in rewards if r.redeemed_at),
            coupons=len(coupon_rows),
            coupons_used=sum(1 for c in coupon_rows if c.used),
            purchases=len(tickets) + len(products),
            spent_cents=sum(t.price_cents for t in tickets) + sum(p.price_cents * p.qty for p in products),
            shares_confirmed=sum(1 for sh in shares if sh.status == "verified"),
            posts=len(posts),
            comments=len(comments),
        ),
        coupons=coupon_rows,
        events=ev[:80],
    )


# ---------------------------------------------------------------- vitrines alugadas


class RentalOut(Camel):
    campaign_id: str
    sponsor_avatar: str | None = None  # foto de perfil do patrocinador
    views: int = 0  # visualizações desta compra (a campanha inteira)
    clicks: int = 0
    ctr: float = 0.0  # cliques / visualizações, em %
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
    price_cents_per_week: int | None = None  # modelo antigo (por semana); hoje o preço é por view e por clique
    view_price_milli: int | None = None
    click_price_milli: int | None = None
    estimated_total_cents: int | None = None  # o que a campanha já consumiu: views x preço da view + cliques x preço do clique


@router.get("/artists/{slug}/rentals", response_model=list[RentalOut])
def rentals(artist: ManagedArtist, db: DB):
    """Todas as vitrines alugadas do ambiente e dos fã clubes: quem alugou, por quanto tempo e qual vitrine."""
    today = date.today()
    q = (
        select(m.Campaign)
        .join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id)
        .where(m.AdSlot.artist_id == artist.id, m.Campaign.status == "approved")
    )
    camps = list(db.scalars(q))
    totals: dict[str, tuple[int, int]] = {}
    if camps:
        for cid, v, k in db.execute(
            select(m.AdStat.campaign_id, func.sum(m.AdStat.views), func.sum(m.AdStat.clicks))
            .where(m.AdStat.campaign_id.in_([c.id for c in camps]))
            .group_by(m.AdStat.campaign_id)
        ):
            totals[cid] = (int(v or 0), int(k or 0))
    out: list[RentalOut] = []
    for c in camps:
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
                campaign_id=c.id,
                sponsor_avatar=sponsor_avatar(c.sponsor),
                views=totals.get(c.id, (0, 0))[0],
                clicks=totals.get(c.id, (0, 0))[1],
                ctr=round(100 * totals.get(c.id, (0, 0))[1] / totals[c.id][0], 2) if totals.get(c.id, (0, 0))[0] else 0.0,
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
                price_cents_per_week=None,
                view_price_milli=c.slot.view_price_milli,
                click_price_milli=c.slot.click_price_milli,
                # quanto a campanha já consumiu: views e cliques até hoje pelo preço da vitrine (milésimos de real → centavos)
                estimated_total_cents=round((totals.get(c.id, (0, 0))[0] * (c.slot.view_price_milli or 0) + totals.get(c.id, (0, 0))[1] * (c.slot.click_price_milli or 0)) / 10),
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


# ---------------------------------------------------------------- vendas da loja


class StoreBuyer(Camel):
    user_id: str | None = None
    name: str
    handle: str = ""
    email: str = ""
    avatar: str | None = None
    size: str = ""
    qty: int
    paid_cents: int  # valor unitário x quantidade
    order_code: str = ""
    delivery: str = ""  # pickup | ship
    at: datetime


class ProductSales(Camel):
    product_id: str
    name: str
    category: str
    sold: int  # unidades vendidas
    revenue_cents: int
    buyers: int  # pessoas diferentes
    stock: int | None = None  # unidades em estoque hoje (vazio = sem controle)
    by_size: dict[str, int] = {}
    last_sale: datetime | None = None
    history: list[StoreBuyer] = []  # as últimas compras, da mais nova para a mais antiga


class StoreAnalytics(Camel):
    revenue_cents: int
    units: int
    orders: int
    buyers: int
    products: list[ProductSales]


@router.get("/artists/{slug}/manage/store/analytics", response_model=StoreAnalytics)
def store_analytics(artist: ManagedArtist, db: DB):
    """Vendas da loja: quanto cada produto já vendeu, o estoque que sobra e quem comprou (do mais recente ao mais antigo)."""
    products = list(db.scalars(select(m.Product).where(m.Product.artist_id == artist.id).order_by(m.Product.position)))
    rows = db.execute(
        select(m.ProductPurchase, m.User, m.StoreOrder)
        .join(m.User, m.User.id == m.ProductPurchase.user_id)
        .outerjoin(m.StoreOrder, m.StoreOrder.id == m.ProductPurchase.order_id)
        .where(m.ProductPurchase.artist_id == artist.id)
        .order_by(m.ProductPurchase.created_at.desc())
    ).all()
    by: dict[str, list[tuple]] = {}
    for pur, user, order in rows:
        by.setdefault(pur.product_id or f"removido:{pur.name}", []).append((pur, user, order))
    names = {p.id: p for p in products}

    def build(key: str, prod: m.Product | None, items: list[tuple]) -> ProductSales:
        sizes: Counter = Counter()
        for pur, _, _ in items:
            if pur.size:
                sizes[pur.size] += pur.qty
        first = items[0][0] if items else None
        return ProductSales(
            product_id=key,
            name=prod.name if prod else (first.name if first else ""),
            category=prod.category if prod else (first.category if first else "roupas"),
            sold=sum(p.qty for p, _, _ in items),
            revenue_cents=sum(p.price_cents * p.qty for p, _, _ in items),
            buyers=len({p.user_id for p, _, _ in items}),
            stock=prod.stock if prod else None,
            by_size=dict(sizes),
            last_sale=first.created_at if first else None,
            history=[
                StoreBuyer(
                    user_id=u.id,
                    name=u.name,
                    handle=u.handle or "",
                    email=u.email,
                    avatar=u.avatar_path or None,
                    size=p.size,
                    qty=p.qty,
                    paid_cents=p.price_cents * p.qty,
                    order_code=o.code if o else "",
                    delivery=o.delivery if o else "",
                    at=p.created_at,
                )
                for p, u, o in items[:100]
            ],
        )

    out = [build(p.id, p, by.get(p.id, [])) for p in products]
    out += [build(k, None, v) for k, v in by.items() if k not in names]
    return StoreAnalytics(
        revenue_cents=sum(p.revenue_cents for p in out),
        units=sum(p.sold for p in out),
        orders=len({o.id for _, _, o in rows if o}),
        buyers=len({pur.user_id for pur, _, _ in rows}),
        products=out,
    )


class StoreDay(Camel):
    day: date
    views: int
    carts: int
    purchases: int  # unidades vendidas
    revenue_cents: int


class StoreProductFunnel(Camel):
    product_id: str
    name: str
    views: int  # visualizações (uma por fã e dia)
    carts: int  # vezes que foi para o carrinho
    removes: int  # vezes que saiu do carrinho
    purchases: int  # unidades vendidas
    buyers: int
    revenue_cents: int
    view_to_cart: float  # % dos fãs que viram e puseram no carrinho
    cart_to_buy: float  # % dos fãs que puseram no carrinho e compraram
    abandoned: int  # fãs que puseram no carrinho e não compraram


class StoreInsights(Camel):
    days: int
    viewers: int  # fãs que viram algum produto
    cart_people: int  # fãs que puseram algo no carrinho
    buyers: int
    views: int
    carts: int
    removes: int
    units: int
    orders: int
    revenue_cents: int
    avg_ticket_cents: int
    items_per_order: float
    view_to_cart: float
    cart_to_buy: float
    abandoned: int  # fãs que puseram no carrinho e não compraram (no período)
    pickup: int  # pedidos para retirar
    ship: int  # pedidos para entregar
    series: list[StoreDay]
    products: list[StoreProductFunnel]
    by_size: dict[str, int]
    by_weekday: list[int]  # unidades vendidas por dia da semana (0 = domingo)
    by_hour: list[int]  # unidades vendidas por hora do dia (0 a 23)


def _pct(a: int, b: int) -> float:
    return round(min(100.0, 100 * a / b), 1) if b else 0.0


@router.get("/artists/{slug}/manage/store/insights", response_model=StoreInsights)
def store_insights(artist: ManagedArtist, db: DB, days: int = 30):
    """Funil e gráficos da loja no período: visualizações, carrinho e compras de cada produto, dia a dia."""
    days = min(max(days, 1), 365)
    br = timezone(timedelta(hours=-3))
    today = datetime.now(br).date()
    first = today - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=br)
    local = lambda dt: dt.astimezone(br)  # noqa: E731

    events = list(db.scalars(select(m.StoreEvent).where(m.StoreEvent.artist_id == artist.id, m.StoreEvent.created_at >= start)))
    rows = db.execute(
        select(m.ProductPurchase, m.StoreOrder)
        .outerjoin(m.StoreOrder, m.StoreOrder.id == m.ProductPurchase.order_id)
        .where(m.ProductPurchase.artist_id == artist.id, m.ProductPurchase.created_at >= start)
    ).all()
    prods = {p.id: p for p in db.scalars(select(m.Product).where(m.Product.artist_id == artist.id).order_by(m.Product.position))}

    per_day = {first + timedelta(days=i): [0, 0, 0, 0] for i in range(days)}  # views, carts, unidades, receita
    for e in events:
        d = local(e.created_at).date()
        if d in per_day and e.kind in ("view", "cart_add"):
            per_day[d][0 if e.kind == "view" else 1] += 1
    sizes: Counter = Counter()
    weekday, hour = [0] * 7, [0] * 24
    for pur, _ in rows:
        t = local(pur.created_at)
        if t.date() in per_day:
            per_day[t.date()][2] += pur.qty
            per_day[t.date()][3] += pur.price_cents * pur.qty
        weekday[(t.weekday() + 1) % 7] += pur.qty
        hour[t.hour] += pur.qty
        if pur.size:
            sizes[pur.size] += pur.qty

    def funnel(pid: str, name: str) -> StoreProductFunnel:
        ev = [e for e in events if e.product_id == pid]
        pu = [p for p, _ in rows if p.product_id == pid]
        viewers = {e.user_id for e in ev if e.kind == "view" and e.user_id}
        carted = {e.user_id for e in ev if e.kind == "cart_add" and e.user_id}
        buyers = {p.user_id for p in pu}
        return StoreProductFunnel(
            product_id=pid,
            name=name,
            views=sum(1 for e in ev if e.kind == "view"),
            carts=sum(1 for e in ev if e.kind == "cart_add"),
            removes=sum(1 for e in ev if e.kind == "cart_remove"),
            purchases=sum(p.qty for p in pu),
            buyers=len(buyers),
            revenue_cents=sum(p.price_cents * p.qty for p in pu),
            view_to_cart=_pct(len(carted), len(viewers)),
            cart_to_buy=_pct(len(carted & buyers), len(carted)),
            abandoned=len(carted - buyers),
        )

    products = [funnel(pid, p.name) for pid, p in prods.items()]
    viewers = {e.user_id for e in events if e.kind == "view" and e.user_id}
    carted = {e.user_id for e in events if e.kind == "cart_add" and e.user_id}
    buyers = {p.user_id for p, _ in rows}
    orders = {o.id: o for _, o in rows if o}
    revenue = sum(p.price_cents * p.qty for p, _ in rows)
    units = sum(p.qty for p, _ in rows)
    return StoreInsights(
        days=days,
        viewers=len(viewers),
        cart_people=len(carted),
        buyers=len(buyers),
        views=sum(1 for e in events if e.kind == "view"),
        carts=sum(1 for e in events if e.kind == "cart_add"),
        removes=sum(1 for e in events if e.kind == "cart_remove"),
        units=units,
        orders=len(orders),
        revenue_cents=revenue,
        avg_ticket_cents=round(sum(o.total_cents for o in orders.values()) / len(orders)) if orders else 0,
        items_per_order=round(units / len(orders), 1) if orders else 0.0,
        view_to_cart=_pct(len(carted), len(viewers)),
        cart_to_buy=_pct(len(carted & buyers), len(carted)),
        abandoned=len(carted - buyers),
        pickup=sum(1 for o in orders.values() if o.delivery == "pickup"),
        ship=sum(1 for o in orders.values() if o.delivery == "ship"),
        series=[StoreDay(day=d, views=v[0], carts=v[1], purchases=v[2], revenue_cents=v[3]) for d, v in per_day.items()],
        products=sorted(products, key=lambda p: (-p.purchases, -p.carts, -p.views)),
        by_size=dict(sizes),
        by_weekday=weekday,
        by_hour=hour,
    )
