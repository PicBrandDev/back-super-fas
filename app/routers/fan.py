"""Área do fã: leitura do conteúdo do fã clube e as ações do fã (postar, girar, assinar…)."""

import random
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import (
    AdSlotOut,
    ArtistOut,
    EventOut,
    FanPostIn,
    GiftOut,
    HomeAdOut,
    PerkOut,
    PostOut,
    PrizeOut,
    ProductOut,
    SpinOut,
    SubscribeIn,
    TrackOut,
    VendorOut,
    ViewerOut,
    ad_slot_out,
    artist_out,
    brl,
    campaign_status,
    event_out,
    initial_of,
    post_out,
)
from ..security import DB, CurrentUser, can_manage, current_user_optional, get_artist_or_404

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


def viewer_out(user: m.User, f: m.Fandom | None) -> ViewerOut:
    return ViewerOut(
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
    if artist:
        a = visible_artist(db, artist, user)
        f = get_fandom(db, a, user, create=user.role == m.ROLE_FAN)
    return viewer_out(user, f)


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
    post = m.Post(artist_id=artist.id, kind=body.kind, author_id=user.id, text=body.text.strip(), url=body.url.strip())
    db.add(post)
    db.commit()
    db.refresh(post)
    return post_out(post, artist)


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
    prizes = db.scalars(select(m.Prize).where(m.Prize.artist_id == artist.id).order_by(m.Prize.position)).all()
    return [PrizeOut(id=p.id, label=p.label, is_retry=p.is_retry or None) for p in prizes]


@router.post("/artists/{slug}/pickap/spin", response_model=SpinOut)
def spin(artist: FanArtist, user: CurrentUser, db: DB):
    """O servidor sorteia o prêmio e desconta o giro."""
    prizes = db.scalars(select(m.Prize).where(m.Prize.artist_id == artist.id)).all()
    if not prizes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A roleta ainda não tem prêmios.")
    f = get_fandom(db, artist, user)
    assert f is not None
    if f.spins <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não tem giros disponíveis.")
    prize = random.choice(prizes)
    f.spins -= 1
    if prize.is_retry:
        f.spins += 1
    f.luck_points += prize.points
    db.commit()
    return SpinOut(
        prize=PrizeOut(id=prize.id, label=prize.label, is_retry=prize.is_retry or None),
        spins_left=f.spins,
        luck_points=f.luck_points,
    )


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
    return [ad_slot_out(db, s) for s in sorted(artist.ad_slots, key=lambda s: s.position)]


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
    return viewer_out(user, f)
