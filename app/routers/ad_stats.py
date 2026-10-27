"""Visualizações e cliques dos anúncios: o app do fã registra, o admin do ambiente vê por patrocinador e campanha."""

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from .. import models as m
from ..schemas import Camel
from ..security import DB, CurrentUser, ManagedArtist
from .fan import FanArtist

router = APIRouter(tags=["Anúncios"])


class TrackIn(Camel):
    kind: Literal["view", "click"]


@router.post("/artists/{slug}/ads/{campaign_id}/track", status_code=status.HTTP_204_NO_CONTENT)
def track_ad(campaign_id: str, body: TrackIn, artist: FanArtist, user: CurrentUser, db: DB):
    """Soma uma visualização ou um clique na campanha (o app manda uma vez por anúncio e sessão)."""
    c = db.get(m.Campaign, campaign_id)
    if not c or c.status != "approved" or c.slot.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada")
    col = m.AdStat.views if body.kind == "view" else m.AdStat.clicks
    where = (m.AdStat.campaign_id == c.id, m.AdStat.day == date.today())
    if not db.execute(update(m.AdStat).where(*where).values({col.key: col + 1})).rowcount:
        db.add(m.AdStat(campaign_id=c.id, day=date.today(), views=int(body.kind == "view"), clicks=int(body.kind == "click")))
    db.commit()


class Point(Camel):
    day: date
    views: int
    clicks: int


class CampaignStats(Camel):
    id: str
    title: str
    slot_name: str
    where: str
    fan_club: str | None = None
    status: str  # live | scheduled | ended
    start: date | None = None
    end: date | None = None
    views: int
    clicks: int
    ctr: float  # cliques / visualizações, em %
    goal_views: int
    goal_clicks: int
    series: list[Point]


class SponsorStats(Camel):
    name: str
    views: int
    clicks: int
    ctr: float
    campaigns: list[CampaignStats]


class AdsAnalytics(Camel):
    days: int
    views: int
    clicks: int
    ctr: float
    series: list[Point]
    sponsors: list[SponsorStats]


def _ctr(views: int, clicks: int) -> float:
    return round(clicks * 100 / views, 2) if views else 0.0


@router.get("/artists/{slug}/ads-analytics", response_model=AdsAnalytics)
def ads_analytics(artist: ManagedArtist, db: DB, days: int = 30):
    """Views e cliques de cada anúncio no período, por patrocinador (campanhas aprovadas de todas as vitrines do ambiente)."""
    days = min(max(days, 1), 365)
    today = date.today()
    first = today - timedelta(days=days - 1)
    camps = list(
        db.scalars(
            select(m.Campaign).join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id).where(m.AdSlot.artist_id == artist.id, m.Campaign.status == "approved")
        )
    )
    rows: dict[str, dict[date, tuple[int, int]]] = {}
    if camps:
        q = select(m.AdStat).where(m.AdStat.campaign_id.in_([c.id for c in camps]), m.AdStat.day >= first)
        for r in db.scalars(q):
            rows.setdefault(r.campaign_id, {})[r.day] = (r.views, r.clicks)
    span = [first + timedelta(days=i) for i in range(days)]

    def series(per_day: dict[date, tuple[int, int]]) -> list[Point]:
        return [Point(day=d, views=per_day.get(d, (0, 0))[0], clicks=per_day.get(d, (0, 0))[1]) for d in span]

    total: dict[date, tuple[int, int]] = {}
    by_sponsor: dict[str, list[CampaignStats]] = {}
    for c in camps:
        per = rows.get(c.id, {})
        v = sum(x[0] for x in per.values())
        k = sum(x[1] for x in per.values())
        for d, (dv, dk) in per.items():
            tv, tk = total.get(d, (0, 0))
            total[d] = (tv + dv, tk + dk)
        st = "ended" if c.end and c.end < today else "scheduled" if c.start and c.start > today else "live"
        by_sponsor.setdefault(c.brand or c.sponsor.brand or c.sponsor.email, []).append(
            CampaignStats(
                id=c.id,
                title=c.title,
                slot_name=c.slot.name,
                where=c.slot.where,
                fan_club=c.slot.club.name if c.slot.club else None,
                status=st,
                start=c.start,
                end=c.end,
                views=v,
                clicks=k,
                ctr=_ctr(v, k),
                goal_views=c.goal_views,
                goal_clicks=c.goal_clicks,
                series=series(per),
            )
        )
    sponsors = [
        SponsorStats(
            name=name,
            views=sum(c.views for c in cs),
            clicks=sum(c.clicks for c in cs),
            ctr=_ctr(sum(c.views for c in cs), sum(c.clicks for c in cs)),
            campaigns=sorted(cs, key=lambda c: -c.views),
        )
        for name, cs in by_sponsor.items()
    ]
    sponsors.sort(key=lambda s: -s.views)
    tv = sum(s.views for s in sponsors)
    tk = sum(s.clicks for s in sponsors)
    return AdsAnalytics(days=days, views=tv, clicks=tk, ctr=_ctr(tv, tk), series=series(total), sponsors=sponsors)
