"""Admin master: fã clubes, vitrines, campanhas e patrocinadores."""

import copy
import re
import unicodedata

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..defaults import BLANK_THEME, DEFAULT_AD_SLOTS, MODULES, NEW_CLUB_COLORS
from ..schemas import (
    AdSlotOut,
    AdSlotPatch,
    ArtistOut,
    ArtistPatch,
    CampaignOut,
    FanClubCreate,
    FanClubCreated,
    SponsorInvited,
    SponsorInviteIn,
    SponsorOut,
    ad_slot_out,
    artist_out,
    campaign_out,
    sponsor_out,
)
from ..security import DB, MasterUser, get_artist_or_404, hash_password, temp_password
from .club_admin import add_club_admin

router = APIRouter(tags=["Admin master"])


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def add_default_slots(db: Session, artist: m.Artist) -> None:
    for i, (key, name, where, fmt, top, height) in enumerate(DEFAULT_AD_SLOTS):
        db.add(
            m.AdSlot(
                artist=artist, key=key, name=name, where=where, format=fmt, diagram_top=top, diagram_height=height, position=i
            )
        )


@router.post("/admin/fan-clubs", response_model=FanClubCreated, status_code=201)
def create_fan_club(body: FanClubCreate, _: MasterUser, db: DB):
    base = slugify(body.name) or "artista"
    taken = set(db.scalars(select(m.Artist.slug)))
    reserved = {"admin", "patrocinador", "login", "cadastro", "sair", "conta", "api"}
    slug, n = base, 2
    while slug in taken or slug in reserved:
        slug, n = f"{base}-{n}", n + 1

    count = len(taken)
    artist = m.Artist(
        slug=slug,
        name=body.name.strip(),
        instagram=body.instagram.strip(),
        status="setup",
        theme=copy.deepcopy(BLANK_THEME),
        brand_color=NEW_CLUB_COLORS[count % len(NEW_CLUB_COLORS)],
        modules={k: True for k in MODULES},
    )
    db.add(artist)
    db.flush()
    add_default_slots(db, artist)

    if body.template == "vc":
        # Copia a estrutura (benefícios de membro e fatias da roleta) do Vintage Culture, sem o visual.
        vc = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        if vc:
            artist.member_price_cents = vc.member_price_cents
            artist.modules = dict(vc.modules or artist.modules)
            for p in db.scalars(select(m.MemberPerk).where(m.MemberPerk.artist_id == vc.id)):
                db.add(m.MemberPerk(artist_id=artist.id, title=p.title, sub=p.sub, position=p.position))
            for p in db.scalars(select(m.Prize).where(m.Prize.artist_id == vc.id)):
                db.add(m.Prize(artist_id=artist.id, label=p.label, is_retry=p.is_retry, points=p.points, position=p.position))

    invites = [add_club_admin(db, artist, str(e), role="Administrador") for e in dict.fromkeys(body.invites)]
    db.commit()
    db.refresh(artist)
    return FanClubCreated(artist=artist_out(db, artist), invites=invites)


@router.patch("/admin/fan-clubs/{slug}", response_model=ArtistOut)
def update_fan_club(slug: str, body: ArtistPatch, _: MasterUser, db: DB):
    artist = get_artist_or_404(db, slug)
    data = body.model_dump(exclude_unset=True)
    if "modules" in data and data["modules"] is not None:
        data["modules"] = {**(artist.modules or {}), **data["modules"]}
    if "theme" in data and data["theme"] is not None:
        data["theme"] = {**artist.theme, **data["theme"]}
    for k, v in data.items():
        if v is not None:
            setattr(artist, k, v)
    db.commit()
    db.refresh(artist)
    return artist_out(db, artist)


@router.delete("/admin/fan-clubs/{slug}", status_code=204)
def delete_fan_club(slug: str, _: MasterUser, db: DB):
    artist = get_artist_or_404(db, slug)
    if artist.status == "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Coloque o fã clube em configuração antes de apagar.")
    db.delete(artist)
    db.commit()


# ---------------------------------------------------------------- vitrines


@router.patch("/artists/{slug}/ad-slots/{key}", response_model=AdSlotOut)
def update_ad_slot(slug: str, key: str, body: AdSlotPatch, _: MasterUser, db: DB):
    artist = get_artist_or_404(db, slug)
    slot = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == artist.id, m.AdSlot.key == key))
    if not slot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vitrine não encontrada.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(slot, k, v)
    db.commit()
    return ad_slot_out(db, slot)


# ---------------------------------------------------------------- campanhas


@router.get("/admin/campaigns", response_model=list[CampaignOut])
def list_campaigns(_: MasterUser, db: DB):
    return [campaign_out(c) for c in db.scalars(select(m.Campaign).order_by(m.Campaign.created_at.desc()))]


def _decide(db: Session, campaign_id: str, decision: str) -> CampaignOut:
    c = db.get(m.Campaign, campaign_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada.")
    c.status = decision
    db.commit()
    return campaign_out(c)


@router.post("/admin/campaigns/{campaign_id}/approve", response_model=CampaignOut)
def approve_campaign(campaign_id: str, _: MasterUser, db: DB):
    return _decide(db, campaign_id, "approved")


@router.post("/admin/campaigns/{campaign_id}/reject", response_model=CampaignOut)
def reject_campaign(campaign_id: str, _: MasterUser, db: DB):
    return _decide(db, campaign_id, "rejected")


# ---------------------------------------------------------------- patrocinadores


@router.get("/admin/sponsors", response_model=list[SponsorOut])
def list_sponsors(_: MasterUser, db: DB):
    return [sponsor_out(s) for s in db.scalars(select(m.Sponsor).order_by(m.Sponsor.created_at.desc()))]


@router.post("/admin/sponsors/invite", response_model=SponsorInvited, status_code=201)
def invite_sponsor(body: SponsorInviteIn, _: MasterUser, db: DB):
    email = body.email.lower()
    if db.scalar(select(m.Sponsor).where(m.Sponsor.email == email)) or db.scalar(
        select(m.User).where(m.User.email == email)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma conta com esse e-mail.")
    sponsor = m.Sponsor(email=email, brand=body.brand.strip(), status="invited")
    password = temp_password()
    user = m.User(
        email=email,
        name=body.brand.strip() or email.split("@")[0],
        password_hash=hash_password(password),
        role=m.ROLE_SPONSOR,
        must_change_password=True,
        sponsor=sponsor,
    )
    db.add_all([sponsor, user])
    db.commit()
    db.refresh(sponsor)
    return SponsorInvited(sponsor=sponsor_out(sponsor), temp_password=password)
