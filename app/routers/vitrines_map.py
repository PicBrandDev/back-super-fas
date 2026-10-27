"""Mapa das vitrines: todas as vitrines do ambiente e dos fã clubes, livres ou ocupadas, para o admin e para o patrocinador.

Grupos: "entrada" (modal ao abrir o app), "roleta" (vídeo antes do giro, anúncio depois do prêmio e fatia patrocinada),
"feed" (entre os posts do feed do cantor e dos fã clubes) e "outras" (home, evento, loja, drops).
"""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import select

from .. import models as m
from ..schemas import Camel, campaign_status
from ..security import DB, ManagedArtist, SponsorUser, get_artist_or_404

router = APIRouter(tags=["Mapa das vitrines"])

GROUP_ORDER = {"entrada": 0, "roleta": 1, "feed": 2, "outras": 3}
ROLETA_KEYS = {"pickup_video", "pickup_resgate", "pickup"}


class Booking(Camel):
    brand: str = ""  # vazio para o patrocinador que não é dono da campanha
    sponsor: str | None = None  # quem alugou (só no admin)
    title: str = ""
    text: str = ""
    cta: str = ""
    url: str = ""
    art: str | None = None
    video: str | None = None
    start: date | None = None
    end: date | None = None
    status: str  # live | scheduled
    mine: bool = False  # a campanha é do patrocinador logado (só no portal do patrocinador)


class VitrineCard(Camel):
    key: str
    name: str
    where: str
    format: str
    group: str  # entrada | roleta | feed | outras
    club_slug: str | None = None  # None = ambiente do cantor
    club_name: str | None = None
    price_cents_per_week: int | None = None
    active: bool = True
    diagram_top: int
    diagram_height: int
    live: Booking | None = None  # no ar agora
    next: Booking | None = None  # a próxima agendada


class VitrinesMap(Camel):
    artist: str
    cards: list[VitrineCard]


def _group(key: str) -> str:
    base = key.split(".", 1)[-1]
    if base == "entrada":
        return "entrada"
    if base in ROLETA_KEYS:
        return "roleta"
    if base == "mural" or base.startswith("feed"):
        return "feed"
    return "outras"


def _booking(c: m.Campaign, state: str, admin: bool, sponsor_id: str | None) -> Booking:
    mine = sponsor_id is not None and c.sponsor_id == sponsor_id
    if not admin and not mine:  # o patrocinador só vê que está ocupada, e até quando
        return Booking(start=c.start, end=c.end, status=state)
    return Booking(
        brand=c.brand or c.sponsor.brand or c.sponsor.email,
        sponsor=(c.brand or c.sponsor.brand or c.sponsor.email) if admin else None,
        title=c.title,
        text=c.text,
        cta=c.cta,
        url=c.url,
        art=c.art_path or None,
        video=c.video_url or None,
        start=c.start,
        end=c.end,
        status=state,
        mine=mine,
    )


def _cards(db, artist: m.Artist, admin: bool, sponsor_id: str | None) -> list[VitrineCard]:
    slots = list(db.scalars(select(m.AdSlot).where(m.AdSlot.artist_id == artist.id)))
    camps = list(db.scalars(select(m.Campaign).where(m.Campaign.slot_id.in_([s.id for s in slots]), m.Campaign.status == "approved"))) if slots else []
    today = date.today()
    by_slot: dict[str, list[m.Campaign]] = {}
    for c in camps:
        by_slot.setdefault(c.slot_id, []).append(c)
    out: list[VitrineCard] = []
    for s in slots:
        live = nxt = None
        for c in sorted(by_slot.get(s.id, []), key=lambda c: (c.start or today)):
            st = campaign_status(c)
            if st == "live" and live is None:
                live = _booking(c, "live", admin, sponsor_id)
            elif st == "approved" and c.start and c.start > today and nxt is None:
                nxt = _booking(c, "scheduled", admin, sponsor_id)
        out.append(
            VitrineCard(
                key=s.key,
                name=s.name,
                where=s.where,
                format=s.format,
                group=_group(s.key),
                club_slug=s.club.slug if s.club else None,
                club_name=s.club.name if s.club else None,
                price_cents_per_week=s.price_cents,
                active=s.active,
                diagram_top=s.diagram_top,
                diagram_height=s.diagram_height,
                live=live,
                next=nxt,
            )
        )
    pos = {s.key: (s.position, s.club.position if s.club else -1) for s in slots}
    out.sort(key=lambda c: (GROUP_ORDER[c.group], c.club_slug is not None, pos[c.key][1], pos[c.key][0]))
    return out


@router.get("/artists/{slug}/vitrines-map", response_model=VitrinesMap)
def admin_map(artist: ManagedArtist, db: DB):
    """Todas as vitrines do ambiente e dos fã clubes, com quem está no ar e quem vem a seguir (admin)."""
    return VitrinesMap(artist=artist.slug, cards=_cards(db, artist, True, None))


@router.get("/sponsor/vitrines-map", response_model=VitrinesMap)
def sponsor_map(user: SponsorUser, db: DB, artist: str):
    """Todas as vitrines de um cantor, livres ou ocupadas. O patrocinador vê a arte só das suas campanhas."""
    a = get_artist_or_404(db, artist)
    return VitrinesMap(artist=a.slug, cards=_cards(db, a, False, user.sponsor_id))
