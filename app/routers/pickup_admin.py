"""PicKup no admin: a roleta ativa, o histórico de giros, o estoque de cada brinde e quem ganhou cada um (só leitura).

O estoque de uma fatia (`Prize.stock`) é editado pelo CRUD de prêmios do fã clube; aqui só se lê.
Cada fã clube tem a sua roleta: `club` escolhe qual (sem ele, a do fã clube master). Giros antigos, de antes de a API
guardar a roleta de cada giro, entram só na roleta do master.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from .. import models as m
from .. import rewards
from ..schemas import Camel
from ..security import DB, ManagedArtist, master_club

router = APIRouter(tags=["PicKup admin"])

PAGE_SIZE = 10
NO_REWARD = ("none", "retry")  # fatias que não geram brinde


class Person(Camel):
    user_id: str | None = None
    name: str
    handle: str = ""
    avatar: str | None = None


class Winner(Person):
    at: datetime
    code: str = ""  # código do brinde (vazio quando a fatia não gera brinde)
    status: str = ""  # available | used | redeemed | expired


class PrizeStat(Camel):
    id: str
    label: str
    kind: str
    percent: int
    points: int
    is_retry: bool
    position: int
    stock: int | None = None  # None = ilimitado
    won: int  # vezes que saiu (unidades entregues)
    people: int  # pessoas diferentes que ganharam
    remaining: int | None = None  # None = ilimitado
    recent: list[Winner]  # os 5 últimos


class Wheel(Camel):
    slug: str
    name: str
    is_master: bool


class LastSpin(Person):
    at: datetime
    prize: str


class Summary(Camel):
    spins: int
    spinners: int
    spins_left: int  # giros que os fãs ainda têm no ambiente
    rewards: int
    last_spin: LastSpin | None = None


class PickupOverview(Camel):
    wheel: Wheel
    wheels: list[Wheel]
    summary: Summary
    prizes: list[PrizeStat]


class SpinRow(Person):
    at: datetime
    prize: str
    kind: str = ""


class SpinPage(Camel):
    total: int
    page: int
    pages: int
    page_size: int = PAGE_SIZE
    items: list[SpinRow]


class WinnerPage(Camel):
    total: int
    page: int
    pages: int
    page_size: int = PAGE_SIZE
    items: list[Winner]


def _wheel(db, artist: m.Artist, slug: str | None) -> m.FanClub:
    if slug:
        club = next((c for c in artist.clubs if c.slug == slug), None)
        if not club:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã clube não encontrado.")
        return club
    mc = master_club(db, artist)
    if not mc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "O ambiente ainda não tem fã clube master.")
    return mc


def _spins_of(club: m.FanClub):
    """Giros usados nesta roleta (os antigos, sem roleta guardada, são da do master)."""
    cond = m.SpinCredit.club_id == club.id
    if club.is_master:
        cond = cond | m.SpinCredit.club_id.is_(None)
    return (m.SpinCredit.artist_id == club.artist_id) & m.SpinCredit.used_at.is_not(None) & cond


def _person(u: m.User | None) -> dict:
    if not u:
        return {"name": "Fã removido"}
    return {"user_id": u.id, "name": u.name, "handle": u.handle or "", "avatar": u.avatar_path or None}


def _at(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _people(db, club: m.FanClub, prize: m.Prize) -> int:
    """Quantas pessoas diferentes ganharam a fatia."""
    if prize.kind in NO_REWARD or prize.is_retry:
        q = select(m.SpinCredit.user_id).where(
            _spins_of(club), (m.SpinCredit.prize_id == prize.id) | (m.SpinCredit.prize_id.is_(None) & (m.SpinCredit.prize_label == prize.label))
        )
    else:
        q = rewards.won_query(club, prize).with_only_columns(m.Reward.user_id)
    return db.scalar(select(func.count(func.distinct(q.subquery().c.user_id)))) or 0


def _winners(db, club: m.FanClub, prize: m.Prize, limit: int | None = None, offset: int = 0) -> tuple[int, list[Winner]]:
    """Quem ganhou a fatia: dos brindes (com código e situação) ou, nas fatias sem brinde, dos giros."""
    if prize.kind in NO_REWARD or prize.is_retry:
        q = select(m.SpinCredit).where(
            _spins_of(club), (m.SpinCredit.prize_id == prize.id) | (m.SpinCredit.prize_id.is_(None) & (m.SpinCredit.prize_label == prize.label))
        ).order_by(m.SpinCredit.used_at.desc())
        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = db.scalars(q.limit(limit).offset(offset) if limit else q.offset(offset)).all()
        users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_({r.user_id for r in rows})))} if rows else {}
        return total, [Winner(**_person(users.get(r.user_id)), at=_at(r.used_at)) for r in rows]
    q = rewards.won_query(club, prize).order_by(m.Reward.created_at.desc())
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.limit(limit).offset(offset) if limit else q.offset(offset)).all()
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_({r.user_id for r in rows})))} if rows else {}
    return total, [Winner(**_person(users.get(r.user_id)), at=_at(r.created_at), code=r.code, status=rewards.status_of(db, r)) for r in rows]


@router.get("/artists/{slug}/manage/pickup", response_model=PickupOverview)
def pickup_overview(artist: ManagedArtist, db: DB, club: str | None = None):
    """A roleta ativa: fatias, estoque de cada brinde, quem ganhou, e os números dos giros."""
    wheel = _wheel(db, artist, club)
    clubs = sorted((c for c in artist.clubs if c.status == "active"), key=lambda c: (not c.is_master, c.position, c.created_at))
    prizes = list(db.scalars(select(m.Prize).where(m.Prize.club_id == wheel.id).order_by(m.Prize.position)))
    stats = []
    for p in prizes:
        total, recent = _winners(db, wheel, p, limit=5)
        stats.append(
            PrizeStat(
                id=p.id, label=p.label, kind=p.kind, percent=p.percent, points=p.points, is_retry=p.is_retry, position=p.position,
                stock=p.stock, won=total, people=_people(db, wheel, p), remaining=None if p.stock is None else max(0, p.stock - total), recent=recent,
            )
        )
    used = _spins_of(wheel)
    total_spins = db.scalar(select(func.count(m.SpinCredit.id)).where(used)) or 0
    spinners = db.scalar(select(func.count(func.distinct(m.SpinCredit.user_id))).where(used)) or 0
    last = db.scalar(select(m.SpinCredit).where(used).order_by(m.SpinCredit.used_at.desc()).limit(1))
    last_spin = None
    if last:
        u = db.get(m.User, last.user_id)
        last_spin = LastSpin(**_person(u), at=_at(last.used_at), prize=last.prize_label or "—")
    left = db.scalar(select(func.count(m.SpinCredit.id)).where(m.SpinCredit.artist_id == artist.id, m.SpinCredit.used_at.is_(None))) or 0
    reward_count = db.scalar(select(func.count(m.Reward.id)).where(m.Reward.club_id == wheel.id)) or 0
    return PickupOverview(
        wheel=Wheel(slug=wheel.slug, name=wheel.name, is_master=wheel.is_master),
        wheels=[Wheel(slug=c.slug, name=c.name, is_master=c.is_master) for c in clubs],
        summary=Summary(spins=total_spins, spinners=spinners, spins_left=left, rewards=reward_count, last_spin=last_spin),
        prizes=stats,
    )


def _page(page: int, total: int) -> tuple[int, int]:
    pages = max(1, -(-total // PAGE_SIZE))
    return min(max(1, page), pages), pages


@router.get("/artists/{slug}/manage/pickup/history", response_model=SpinPage)
def pickup_history(artist: ManagedArtist, db: DB, club: str | None = None, q: str = "", page: int = 1):
    """Quem girou a roleta, do último a girar para o primeiro, de 10 em 10. `q` busca pelo nome."""
    wheel = _wheel(db, artist, club)
    base = select(m.SpinCredit, m.User).join(m.User, m.User.id == m.SpinCredit.user_id).where(_spins_of(wheel))
    term = q.strip().lower()
    if term:
        like = f"%{term}%"
        base = base.where(func.lower(m.User.name).like(like) | func.lower(m.User.handle).like(like) | func.lower(m.User.email).like(like))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    page, pages = _page(page, total)
    rows = db.execute(base.order_by(m.SpinCredit.used_at.desc()).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).all()
    kinds = {p.id: p.kind for p in db.scalars(select(m.Prize).where(m.Prize.club_id == wheel.id))}
    by_label = {p.label: p.kind for p in db.scalars(select(m.Prize).where(m.Prize.club_id == wheel.id))}
    return SpinPage(
        total=total,
        page=page,
        pages=pages,
        items=[
            SpinRow(**_person(u), at=_at(c.used_at), prize=c.prize_label or "—", kind=kinds.get(c.prize_id or "") or by_label.get(c.prize_label, ""))
            for c, u in rows
        ],
    )


@router.get("/artists/{slug}/manage/pickup/prizes/{prize_id}/winners", response_model=WinnerPage)
def prize_winners(prize_id: str, artist: ManagedArtist, db: DB, page: int = 1):
    """Todas as pessoas que ganharam uma fatia da roleta (cupom, ingresso, brinde...), a mais recente primeiro, de 10 em 10."""
    prize = db.get(m.Prize, prize_id)
    club = next((c for c in artist.clubs if prize and c.id == prize.club_id), None)
    if not prize or not club:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prêmio não encontrado.")
    total, _ = _winners(db, club, prize, limit=1)
    page, pages = _page(page, total)
    _, items = _winners(db, club, prize, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    return WinnerPage(total=total, page=page, pages=pages, items=items)


_ = date  # (mantido para quem edita datas aqui)
