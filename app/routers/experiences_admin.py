"""Experiências de um show no admin: quantas pessoas compraram cada uma e a lista de compradores (só leitura).

Não se vende mais ingresso pelo app (a ticketeira faz isso): o pacote vende experiências (jantar, camarim, pré-esquenta,
after, hotel e transfer). Compras antigas, de antes dessa mudança, não guardavam as experiências em separado: nelas a
experiência é reconhecida pelo nome no rótulo da compra.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from .. import models as m
from ..defaults import ADDON_LABELS
from ..schemas import Camel
from ..security import DB, ManagedArtist

router = APIRouter(tags=["Experiências no admin"])

PAGE_SIZE = 10


class Buyer(Camel):
    user_id: str | None = None
    name: str
    handle: str = ""
    email: str = ""
    avatar: str | None = None
    package: str
    agency: str
    at: datetime
    paid_cents: int
    coupon: str = ""
    experiences: list[str]  # tudo o que essa pessoa comprou nessa compra


class ExperienceStat(Camel):
    key: str
    label: str
    offered_in: list[str]  # pacotes que vendem a experiência
    purchases: int  # compras que incluem a experiência
    people: int  # pessoas diferentes que compraram
    sold_out: bool = False  # esgotada em todos os pacotes que a vendem


class ExperiencesOverview(Camel):
    event_id: str
    city: str
    date: str
    purchases: int  # compras do show (todas as experiências)
    people: int
    revenue_cents: int
    experiences: list[ExperienceStat]


class BuyerPage(Camel):
    total: int
    page: int
    pages: int
    page_size: int = PAGE_SIZE
    label: str
    items: list[Buyer]


def _event(db, artist: m.Artist, event_id: str) -> m.Event:
    e = db.get(m.Event, event_id)
    if not e or e.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show não encontrado.")
    return e


def _keys(t: m.TicketPurchase) -> list[str]:
    """Experiências da compra: as gravadas ou, nas compras antigas, as reconhecidas pelo nome no rótulo."""
    if t.addons:
        return list(t.addons)
    return [k for k, label in ADDON_LABELS.items() if label in (t.label or "")]


def _at(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@router.get("/artists/{slug}/manage/events/{event_id}/experiences", response_model=ExperiencesOverview)
def experiences_overview(event_id: str, artist: ManagedArtist, db: DB):
    """Quantas compras e quantas pessoas cada experiência do show tem (as vendidas pelos pacotes e as já compradas)."""
    e = _event(db, artist, event_id)
    purchases = list(db.scalars(select(m.TicketPurchase).where(m.TicketPurchase.event_id == e.id)))
    offered: dict[str, list[m.EventPackage]] = {}
    for p in e.packages:
        for a in p.addons or []:
            offered.setdefault(a["key"], []).append(p)
    keys = list(offered) + [k for k in {k for t in purchases for k in _keys(t)} if k not in offered]
    order = list(ADDON_LABELS)
    keys.sort(key=lambda k: order.index(k) if k in order else 99)
    stats = []
    for k in keys:
        mine = [t for t in purchases if k in _keys(t)]
        pk = offered.get(k, [])
        stats.append(
            ExperienceStat(
                key=k,
                label=ADDON_LABELS.get(k, k),
                offered_in=[p.name for p in pk],
                purchases=len(mine),
                people=len({t.user_id for t in mine}),
                sold_out=bool(pk) and all(next((a for a in (p.addons or []) if a["key"] == k), {}).get("sold_out") for p in pk),
            )
        )
    return ExperiencesOverview(
        event_id=e.id,
        city=e.city,
        date=e.date.isoformat(),
        purchases=len(purchases),
        people=len({t.user_id for t in purchases}),
        revenue_cents=sum(t.price_cents for t in purchases),
        experiences=stats,
    )


@router.get("/artists/{slug}/manage/events/{event_id}/experiences/{key}/buyers", response_model=BuyerPage)
def experience_buyers(event_id: str, key: str, artist: ManagedArtist, db: DB, q: str = "", page: int = 1):
    """Quem comprou uma experiência do show, do mais recente para o mais antigo, de 10 em 10. `q` busca por nome, @ ou e-mail."""
    e = _event(db, artist, event_id)
    rows = [t for t in db.scalars(select(m.TicketPurchase).where(m.TicketPurchase.event_id == e.id).order_by(m.TicketPurchase.created_at.desc())) if key in _keys(t)]
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_({t.user_id for t in rows})))} if rows else {}
    term = q.strip().lower()
    if term:
        rows = [t for t in rows if (u := users.get(t.user_id)) and term in f"{u.name} {u.handle} {u.email}".lower()]
    total = len(rows)
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(1, page), pages)
    chunk = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    out = []
    for t in chunk:
        u = users.get(t.user_id)
        out.append(
            Buyer(
                user_id=u.id if u else None,
                name=u.name if u else "Fã removido",
                handle=(u.handle or "") if u else "",
                email=u.email if u else "",
                avatar=(u.avatar_path or None) if u else None,
                package=t.package_name,
                agency=t.agency_name,
                at=_at(t.created_at),
                paid_cents=t.price_cents,
                coupon=t.coupon_code,
                experiences=[ADDON_LABELS.get(k, k) for k in _keys(t)] or [t.label],
            )
        )
    return BuyerPage(total=total, page=page, pages=pages, label=ADDON_LABELS.get(key, key), items=out)
