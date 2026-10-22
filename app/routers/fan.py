"""Área do fã: leitura do conteúdo do fã clube e as ações do fã (postar, girar, assinar…)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import (
    AdSlotOut,
    ArtistOut,
    CheckoutIn,
    CheckoutOut,
    EventOut,
    FanPostIn,
    GiftOut,
    HomeAdOut,
    MyTicketOut,
    PackageItemOut,
    PackageOut,
    PerkOut,
    PostOut,
    PrizeOut,
    ProductOut,
    PurchaseIn,
    SpinCreditOut,
    SpinOut,
    SubscribeIn,
    TicketOut,
    TrackOut,
    VendorOut,
    ViewerOut,
    ad_slot_out,
    artist_out,
    br_date,
    brl,
    campaign_status,
    event_out,
    initial_of,
    post_out,
)
from ..security import DB, CurrentUser, can_manage, current_user_optional, forbidden, get_artist_or_404, master_club

router = APIRouter(tags=["Fã clube"])


def visible_artist(db: Session, slug: str, user: m.User | None) -> m.Artist:
    """Fã clube em configuração só aparece para quem administra."""
    artist = get_artist_or_404(db, slug)
    if artist.status != "active" and not (user and can_manage(db, user, artist)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã clube não encontrado.")
    return artist


def fan_artist(slug: str, user: CurrentUser, db: DB) -> m.Artist:
    return visible_artist(db, slug, user)


FanArtist = Annotated[m.Artist, Depends(fan_artist)]


def get_fandom(db: Session, artist: m.Artist, user: m.User, create: bool = True) -> m.Fandom | None:
    f = db.scalar(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == user.id))
    if not f and create:
        f = m.Fandom(artist_id=artist.id, user_id=user.id)
        db.add(f)
        db.commit()
        db.refresh(f)
    return f


def ticket_out(t: m.TicketPurchase) -> MyTicketOut:
    return MyTicketOut(
        id=t.id,
        event_id=t.event_id,
        event=event_out(t.event),
        package_name=t.package_name,
        agency_name=t.agency_name,
        label=t.label,
        kind=t.kind,
        price_cents=t.price_cents,
        includes_transfer=t.kind in ("transfer", "seal", "photo"),
        includes_seal=t.kind in ("seal", "photo"),
        includes_photo_finder=t.kind == "photo",
        bought=br_date(t.created_at.date()),
    )


def viewer_out(user: m.User, f: m.Fandom | None, artist: m.Artist | None = None) -> ViewerOut:
    clubs = sorted(mb.club.slug for mb in user.clubs if artist and mb.club.artist_id == artist.id)
    return ViewerOut(
        clubs=clubs,
        name=user.name,
        handle=user.handle or user.email.split("@")[0],
        initial=initial_of(user.name),
        luck_points=f.luck_points if f else 0,
        spins=f.spins if f else 0,
        pending_gifts=0,
        is_member=bool(f and f.member_status == "active"),
    )


# ---------------------------------------------------------------- artistas


@router.get("/artists", response_model=list[ArtistOut])
def list_artists(db: DB, user: Annotated[m.User | None, Depends(current_user_optional)]):
    artists = db.scalars(select(m.Artist).order_by(m.Artist.created_at)).all()
    return [artist_out(db, a) for a in artists if a.status == "active" or (user and can_manage(db, user, a))]


@router.get("/artists/{slug}", response_model=ArtistOut)
def get_artist(slug: str, db: DB, user: Annotated[m.User | None, Depends(current_user_optional)]):
    return artist_out(db, visible_artist(db, slug, user))


# ---------------------------------------------------------------- eu


@router.get("/me", response_model=ViewerOut)
def me(user: CurrentUser, db: DB, artist: str | None = None):
    f = None
    a = None
    if artist:
        a = visible_artist(db, artist, user)
        f = get_fandom(db, a, user, create=user.role == m.ROLE_FAN)
    return viewer_out(user, f, a)


@router.get("/me/fandoms", response_model=list[str])
def my_fandoms(user: CurrentUser, db: DB, artist: str | None = None):
    names = [f.artist.name for f in user.fandoms if f.artist.slug != artist and f.artist.status == "active"]
    return sorted(names)


# ---------------------------------------------------------------- mural


@router.get("/artists/{slug}/posts", response_model=list[PostOut])
def list_posts(artist: FanArtist, db: DB, kind: str | None = None):
    q = select(m.Post).where(m.Post.artist_id == artist.id)
    if kind:
        q = q.where(m.Post.kind == kind)
    posts = db.scalars(q.order_by(m.Post.created_at.desc()).limit(100)).all()
    return [post_out(p, artist) for p in posts]


@router.post("/artists/{slug}/posts", response_model=PostOut, status_code=201)
def create_fan_post(body: FanPostIn, artist: FanArtist, user: CurrentUser, db: DB):
    """Post do fã no mural de um fã clube (sem `club`, vai para o fã clube master)."""
    from .. import spins as spin_lib
    from .clubs import can_manage_club, get_club_or_404, is_member

    club = get_club_or_404(db, artist, body.club) if body.club else master_club(db, artist)
    if not club:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este cantor ainda não tem fã clube.")
    if not is_member(db, club, user) and not can_manage_club(db, user, club):
        raise forbidden("Entre no fã clube para postar no mural dele.")
    post = m.Post(
        artist_id=artist.id, club_id=club.id, kind=body.kind, author_id=user.id, text=body.text.strip(), url=body.url.strip()
    )
    db.add(post)
    f = get_fandom(db, artist, user)
    assert f is not None
    rewarded = spin_lib.grant_for_post(db, f, club.name)
    db.commit()
    db.refresh(post)
    out = post_out(post, artist)
    out.reward_spin = rewarded
    return out


# ---------------------------------------------------------------- agenda


def _event(db: Session, artist: m.Artist, event_id: str) -> m.Event:
    e = db.get(m.Event, event_id)
    if not e or e.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evento não encontrado.")
    return e


@router.get("/artists/{slug}/events", response_model=list[EventOut])
def list_events(artist: FanArtist, db: DB):
    events = db.scalars(select(m.Event).where(m.Event.artist_id == artist.id).order_by(m.Event.date)).all()
    return [event_out(e) for e in events]


@router.get("/artists/{slug}/events/{event_id}", response_model=EventOut)
def get_event(event_id: str, artist: FanArtist, db: DB):
    return event_out(_event(db, artist, event_id))


@router.get("/artists/{slug}/events/{event_id}/vendors", response_model=list[VendorOut])
def list_vendors(event_id: str, artist: FanArtist, db: DB):
    e = _event(db, artist, event_id)
    return [
        VendorOut(id=v.id, name=v.name, type=v.type, tag=v.tag, price_label=v.price_label, url=v.url or "#")
        for v in sorted(e.vendors, key=lambda v: v.position)
    ]


@router.get("/artists/{slug}/events/{event_id}/tickets", response_model=list[TicketOut])
def list_tickets(event_id: str, artist: FanArtist, db: DB):
    """Tipos de ingresso avulsos do show, cada um com o seu preço."""
    e = _event(db, artist, event_id)
    return [
        TicketOut(id=t.id, label=t.label, description=t.description, price_cents=t.price_cents, sold_out=t.sold_out)
        for t in e.tickets
    ]


@router.get("/artists/{slug}/events/{event_id}/packages", response_model=list[PackageOut])
def list_packages(event_id: str, artist: FanArtist, db: DB):
    """Pacotes das agências parceiras do show (ingressos de vários tipos e transfer)."""
    e = _event(db, artist, event_id)
    out = []
    for p in e.packages:
        if not p.active or not p.agency.active:
            continue
        items = [PackageItemOut(kind=i["kind"], label=i["label"], price_cents=i["price_cents"], sold_out=i.get("sold_out", False)) for i in (p.items or [])]
        prices = [i.price_cents for i in items if not i.sold_out]
        out.append(
            PackageOut(
                id=p.id,
                name=p.name,
                description=p.description,
                agency_name=p.agency.name,
                agency_contact=p.agency.contact,
                agency_url=p.agency.url,
                url=p.url or p.agency.url,
                transfer_details=p.transfer_details,
                has_transfer=any(i.kind in ("transfer", "seal", "photo") for i in items),
                from_price_cents=min(prices) if prices else None,
                items=items,
            )
        )
    return out


@router.get("/artists/{slug}/events/{event_id}/gifts", response_model=list[GiftOut])
def list_gifts(event_id: str, artist: FanArtist, db: DB):
    e = _event(db, artist, event_id)
    return [
        GiftOut(id=g.id, name=g.name, phase=g.phase, qty_label=g.qty_label or None)
        for g in sorted(e.gifts, key=lambda g: g.position)
    ]


@router.post("/artists/{slug}/events/{event_id}/luck/join")
def join_luck(event_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    e = _event(db, artist, event_id)
    exists = db.scalar(select(m.EventEntry).where(m.EventEntry.event_id == e.id, m.EventEntry.user_id == user.id))
    if not exists:
        db.add(m.EventEntry(event_id=e.id, user_id=user.id))
        db.commit()
    return {"joined": True}


# ---------------------------------------------------------------- PicKap, loja, drops


@router.get("/artists/{slug}/pickap/prizes", response_model=list[PrizeOut])
def list_prizes(artist: FanArtist, db: DB):
    """Roleta do fã clube master (cada fã clube tem a sua em /clubs/{club}/pickap)."""
    mc = master_club(db, artist)
    prizes = db.scalars(select(m.Prize).where(m.Prize.club_id == mc.id).order_by(m.Prize.position)).all() if mc else []
    return [PrizeOut(id=p.id, label=p.label, is_retry=p.is_retry or None) for p in prizes]


@router.get("/artists/{slug}/pickap/spins", response_model=list[SpinCreditOut])
def list_spins(artist: FanArtist, user: CurrentUser, db: DB):
    """Os giros do fã, cada um com o motivo (compra de ingresso, boas-vindas...)."""
    from .. import spins as spin_lib

    f = get_fandom(db, artist, user)
    assert f is not None
    out = spin_lib.out(db, f)
    db.commit()
    return out


@router.post("/artists/{slug}/store/checkout", response_model=CheckoutOut, status_code=201)
def store_checkout(body: CheckoutIn, artist: FanArtist, user: CurrentUser, db: DB):
    """Compra da sacola da loja (simulada): registra os produtos e dá 1 giro da roleta por camiseta."""
    from .. import spins as spin_lib

    products = [db.get(m.Product, pid) for pid in dict.fromkeys(body.product_ids)]
    if any(p is None or p.artist_id != artist.id for p in products):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto não encontrado.")
    f = get_fandom(db, artist, user)
    assert f is not None
    granted = 0
    for p in products:
        assert p is not None
        db.add(m.ProductPurchase(artist_id=artist.id, user_id=user.id, product_id=p.id, name=p.name, category=p.category, price_cents=p.price_cents or 0))
        if p.category == "roupas":
            spin_lib.grant(db, f, f"Compra de camiseta · {p.name}")
            granted += 1
    db.commit()
    return CheckoutOut(items=len(products), spins_granted=granted)


@router.post("/artists/{slug}/events/{event_id}/purchases", response_model=MyTicketOut, status_code=201)
def buy_ticket(event_id: str, body: PurchaseIn, artist: FanArtist, user: CurrentUser, db: DB):
    """Compra de ingresso (simulada): registra o ingresso do fã e dá 1 giro da roleta, com o motivo."""
    from .. import spins as spin_lib

    e = _event(db, artist, event_id)
    pkg = db.get(m.EventPackage, body.package_id)
    if not pkg or pkg.event_id != e.id or not pkg.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pacote não encontrado.")
    items = pkg.items or []
    if body.item >= len(items):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Opção inválida.")
    item = items[body.item]
    if item.get("sold_out"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Essa opção está esgotada.")
    purchase = m.TicketPurchase(
        artist_id=artist.id,
        user_id=user.id,
        event_id=e.id,
        package_name=pkg.name,
        agency_name=pkg.agency.name,
        label=item["label"],
        kind=item["kind"],
        price_cents=item["price_cents"],
    )
    db.add(purchase)
    f = get_fandom(db, artist, user)
    assert f is not None
    spin_lib.grant(db, f, f"Compra de ingresso · {e.city} ({e.date.day:02d}/{e.date.month:02d}) · {item['label']}")
    db.commit()
    db.refresh(purchase)
    return ticket_out(purchase)


@router.get("/artists/{slug}/me/tickets", response_model=list[MyTicketOut])
def my_tickets(artist: FanArtist, user: CurrentUser, db: DB):
    """Os ingressos que o fã comprou neste ambiente, dos shows mais próximos para os mais antigos."""
    q = select(m.TicketPurchase).where(m.TicketPurchase.artist_id == artist.id, m.TicketPurchase.user_id == user.id)
    rows = list(db.scalars(q))
    rows.sort(key=lambda t: (t.event.date, t.created_at))
    return [ticket_out(t) for t in rows]


@router.post("/artists/{slug}/pickap/spin", response_model=SpinOut)
def spin(artist: FanArtist, user: CurrentUser, db: DB):
    """Gira a roleta do fã clube master."""
    from .clubs import spin_wheel

    mc = master_club(db, artist)
    if not mc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A roleta ainda não tem prêmios.")
    return spin_wheel(db, mc, user)


@router.get("/artists/{slug}/products", response_model=list[ProductOut])
def list_products(artist: FanArtist, db: DB):
    items = db.scalars(select(m.Product).where(m.Product.artist_id == artist.id).order_by(m.Product.position)).all()
    return [ProductOut(id=p.id, name=p.name, category=p.category, price_label=brl(p.price_cents), color=p.color) for p in items]


@router.get("/artists/{slug}/tracks", response_model=list[TrackOut])
def list_tracks(artist: FanArtist, db: DB):
    items = db.scalars(select(m.Track).where(m.Track.artist_id == artist.id).order_by(m.Track.position)).all()
    return [
        TrackOut(
            id=t.id,
            num=f"{i + 1:02d}",
            title=t.title,
            meta=t.meta,
            votes=t.votes,
            release_label=t.release_label,
            duration_sec=t.duration_sec,
        )
        for i, t in enumerate(items)
    ]


# ---------------------------------------------------------------- mídia e membros


@router.get("/artists/{slug}/ads/home", response_model=HomeAdOut | None)
def home_ad(artist: FanArtist, db: DB):
    slot = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == artist.id, m.AdSlot.key == "home"))
    if not slot or not slot.active:
        return None
    q = select(m.Campaign).where(m.Campaign.slot_id == slot.id, m.Campaign.status == "approved")
    for c in db.scalars(q.order_by(m.Campaign.created_at)):
        if campaign_status(c) == "live":
            return HomeAdOut(sponsor=c.brand or c.sponsor.brand, title=c.title, text=c.text, cta=c.cta or "Saiba mais", url=c.url or "#")
    return None


@router.get("/artists/{slug}/ad-slots", response_model=list[AdSlotOut])
def list_ad_slots(artist: FanArtist, db: DB):
    env_slots = [s for s in artist.ad_slots if s.club_id is None]
    return [ad_slot_out(db, s) for s in sorted(env_slots, key=lambda s: s.position)]


@router.get("/artists/{slug}/membership/perks", response_model=list[PerkOut])
def list_perks(artist: FanArtist, db: DB):
    items = db.scalars(select(m.MemberPerk).where(m.MemberPerk.artist_id == artist.id).order_by(m.MemberPerk.position)).all()
    return [PerkOut(title=p.title, sub=p.sub) for p in items]


@router.post("/artists/{slug}/membership/subscribe", response_model=ViewerOut)
def subscribe(body: SubscribeIn, artist: FanArtist, user: CurrentUser, db: DB):
    """Assinatura simulada: ainda não há cobrança de verdade, o fã vira membro na hora."""
    f = get_fandom(db, artist, user)
    assert f is not None
    f.member_status = "active"
    f.member_since = f.member_since or date.today()
    f.payment = "Pix" if body.method == "pix" else "Cartão"
    db.commit()
    return viewer_out(user, f, artist)
