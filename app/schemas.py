"""Formatos de entrada e saída da API.

Os campos saem em camelCase, iguais aos tipos do front (src/lib/types.ts).
"""

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---------------------------------------------------------------- utilidades


def brl(cents: int | None) -> str:
    if cents is None:
        return "R$ [PREÇO]"
    s = f"{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


WEEKDAYS = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]
MONTHS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def time_label(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - when).total_seconds()
    if secs < 60:
        return "agora"
    if secs < 3600:
        return f"há {int(secs // 60)} min"
    if secs < 86400:
        return f"há {int(secs // 3600)} h"
    days = int(secs // 86400)
    if days == 1:
        return "ontem"
    if days < 7:
        return f"há {days} dias"
    return when.strftime("%d/%m/%Y")


def initial_of(name: str) -> str:
    return (name.strip()[:1] or "?").upper()


def br_date(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


# ---------------------------------------------------------------- auth


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RegisterIn(Camel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    handle: str = Field(default="", max_length=60)
    city: str = Field(default="", max_length=80)
    # Endereço (o front exige no cadastro; a API aceita vazio para contas antigas e scripts).
    zip_code: str = Field(default="", max_length=9)
    street: str = Field(default="", max_length=160)
    number: str = Field(default="", max_length=20)
    complement: str = Field(default="", max_length=80)
    neighborhood: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=2)  # UF
    artist: str | None = None  # slug do fã clube escolhido no cadastro


class ChangePasswordIn(Camel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class SessionUser(Camel):
    id: str
    name: str
    email: str
    role: str
    artists: list[str]  # cantores cujo ambiente administra (equipe do fã clube master)
    clubs: list[str]  # fã clubes da equipe, como "cantor/clube"
    sponsor_id: str | None = None
    must_change_password: bool = False


class TokenOut(Camel):
    token: str
    user: SessionUser


def session_user(u: m.User) -> SessionUser:
    return SessionUser(
        id=u.id,
        name=u.name,
        email=u.email,
        role=u.role,
        artists=sorted({st.club.artist.slug for st in u.staff_of if st.club.is_master}),
        clubs=sorted(f"{st.club.artist.slug}/{st.club.slug}" for st in u.staff_of),
        sponsor_id=u.sponsor_id,
        must_change_password=u.must_change_password,
    )


# ---------------------------------------------------------------- artistas


class ArtistOut(Camel):
    id: str
    slug: str
    name: str
    initial: str
    fan_club_name: str
    instagram: str | None = None
    status: str
    theme: dict
    member_price_cents: int
    members: str
    ad_slots_summary: str
    brand_color: str
    modules: dict
    clubs: int  # quantos fã clubes o ambiente tem


def slot_occupied(db: Session, slot: m.AdSlot) -> bool:
    """Ocupada = tem campanha aprovada no ar hoje."""
    q = select(m.Campaign).where(m.Campaign.slot_id == slot.id, m.Campaign.status == "approved")
    return any(campaign_status(c) == "live" for c in db.scalars(q))


def artist_out(db: Session, a: m.Artist) -> ArtistOut:
    members = db.scalar(
        select(func.count()).select_from(m.Fandom).where(m.Fandom.artist_id == a.id, m.Fandom.member_status == "active")
    )
    slots = [s for s in a.ad_slots if s.club_id is None]  # vitrines do ambiente
    occupied = sum(1 for s in slots if slot_occupied(db, s))
    summary = f"{occupied} de {len(slots)} ocupadas" if slots else "Não configuradas"
    return ArtistOut(
        id=a.id,
        slug=a.slug,
        name=a.name,
        initial=initial_of(a.name),
        fan_club_name=a.fan_club_name,
        instagram=a.instagram or None,
        status=a.status,
        theme=a.theme,
        member_price_cents=a.member_price_cents,
        members=str(members or 0),
        ad_slots_summary=summary,
        brand_color=a.brand_color,
        modules=a.modules or {},
        clubs=len(a.clubs),
    )


class ArtistPatch(Camel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    fan_club_name: str | None = None
    instagram: str | None = None
    status: Literal["active", "setup"] | None = None
    member_price_cents: int | None = Field(default=None, ge=0)
    brand_color: str | None = None
    modules: dict[str, bool] | None = None
    theme: dict | None = None


class FanClubCreate(Camel):
    name: str = Field(min_length=2, max_length=120)
    instagram: str = ""
    template: Literal["blank", "vc"] = "blank"
    invites: list[EmailStr] = Field(default_factory=list, max_length=10)


class ClubRef(Camel):
    slug: str
    name: str


class InviteOut(Camel):
    email: str
    temp_password: str | None  # None = a pessoa já tinha conta e só foi vinculada
    email_sent: bool = False  # convite de dono enviado por e-mail


class FanClubCreated(Camel):
    artist: ArtistOut
    invites: list[InviteOut]


class ClubAdminOut(Camel):
    id: str
    user_id: str
    name: str
    email: str
    role: str
    pending: bool  # ainda não trocou a senha provisória


class AdminInviteIn(Camel):
    email: EmailStr
    name: str = ""
    role: str = "Administrador"


# ---------------------------------------------------------------- fã


class ViewerOut(Camel):
    name: str
    handle: str
    initial: str
    luck_points: int
    spins: int
    pending_gifts: int
    is_member: bool
    clubs: list[str] = []  # fã clubes (slugs) em que o fã entrou neste cantor


class AuthorOut(Camel):
    name: str
    handle: str
    initial: str
    official: bool | None = None


class PostOut(Camel):
    id: str
    kind: str
    author: AuthorOut
    time_label: str
    text: str
    has_image: bool | None = None
    quote: str | None = None
    url: str | None = None
    club: ClubRef | None = None  # fã clube do post (vazio = oficial)
    image: dict | None = None  # {"src": "/uploads/abc.jpg", "alt": "..."} quando o post tem foto enviada
    likes: int
    comments: int
    reposts: int
    views: int = 0


def post_out(p: m.Post, artist: m.Artist) -> PostOut:
    if p.official or not p.author:
        author = AuthorOut(name=artist.name, handle="Artista", initial=initial_of(artist.name), official=True)
    else:
        author = AuthorOut(name=p.author.name, handle=p.author.handle or "", initial=initial_of(p.author.name))
    return PostOut(
        id=p.id,
        kind=p.kind,
        author=author,
        time_label=time_label(p.created_at),
        text=p.text,
        has_image=(p.has_image or bool(p.image_path)) or None,
        image={"src": p.image_path, "alt": f"Foto do post de {artist.name}"} if p.image_path else None,
        quote=p.quote or None,
        url=p.url or None,
        club=ClubRef(slug=p.club.slug, name=p.club.name) if p.club else None,
        likes=p.likes,
        comments=p.comments,
        reposts=p.reposts,
        views=p.views,
    )


class FanPostIn(Camel):
    kind: Literal["galera", "instagram"] = "galera"
    club: str | None = None  # slug do fã clube (vazio = master)
    text: str = Field(min_length=1, max_length=2000)
    url: str = Field(default="", max_length=500)


class EventOut(Camel):
    id: str
    date: date
    weekday: str
    day: str
    month: str
    month_key: str
    city: str
    venue: str
    time: str
    address: str
    doors_open: str
    age_rating: str
    lineup: str
    gifts_count: int
    status: str


def event_out(e: m.Event) -> EventOut:
    month = MONTHS[e.date.month - 1]
    return EventOut(
        id=e.id,
        date=e.date,
        weekday=WEEKDAYS[e.date.weekday()],
        day=f"{e.date.day:02d}",
        month=month,
        month_key=month.lower(),
        city=e.city,
        venue=e.venue,
        time=e.time,
        address=e.address,
        doors_open=e.doors_open,
        age_rating=e.age_rating,
        lineup=e.lineup,
        gifts_count=len(e.gifts),
        status=e.status,
    )


class VendorOut(Camel):
    id: str
    name: str
    type: str
    tag: str
    price_label: str
    url: str


class GiftOut(Camel):
    id: str
    name: str
    phase: str
    qty_label: str | None = None


class PrizeOut(Camel):
    id: str
    label: str
    is_retry: bool | None = None


class ProductOut(Camel):
    id: str
    name: str
    category: str
    price_label: str
    color: str


class TrackOut(Camel):
    id: str
    num: str
    title: str
    meta: str
    votes: int
    release_label: str
    duration_sec: int


class HomeAdOut(Camel):
    sponsor: str
    title: str
    text: str
    cta: str
    url: str


class PerkOut(Camel):
    title: str
    sub: str


class MemberOut(Camel):
    id: str
    name: str
    handle: str
    status: str
    since: str
    payment: str
    points: int
    city: str


class SubscribeIn(Camel):
    method: Literal["pix", "card"] = "pix"


class SpinOut(Camel):
    prize: PrizeOut
    spins_left: int
    luck_points: int


# ---------------------------------------------------------------- mídia


class AdSlotOut(Camel):
    id: str  # a "key" da vitrine (home, mural…), única dentro do fã clube
    name: str
    where: str
    format: str
    price_label: str
    price_cents: int | None = None
    occupied: bool
    active: bool
    diagram: dict


def ad_slot_out(db: Session, s: m.AdSlot) -> AdSlotOut:
    price = f"{brl(s.price_cents)} / semana"
    return AdSlotOut(
        id=s.key,
        name=s.name,
        where=s.where,
        format=s.format,
        price_label=price,
        price_cents=s.price_cents,
        occupied=slot_occupied(db, s),
        active=s.active,
        diagram={"top": s.diagram_top, "height": s.diagram_height},
    )


class AdSlotPatch(Camel):
    active: bool | None = None
    price_cents: int | None = Field(default=None, ge=0)
    name: str | None = None
    where: str | None = None
    format: str | None = None


class CampaignOut(Camel):
    id: str
    sponsor: str
    slot_name: str
    club: str  # nome do cantor
    club_slug: str  # slug do cantor
    fan_club: str | None = None  # fã clube da vitrine (vazio = ambiente do cantor)
    fan_club_slug: str | None = None
    title: str
    text: str
    cta: str
    url: str
    period: str
    start: date | None = None
    end: date | None = None
    art_url: str | None = None  # caminho relativo à API (ex.: /uploads/abc.png)
    status: str  # live | approved | pending | rejected


def campaign_status(c: m.Campaign) -> str:
    if c.status != "approved":
        return c.status
    today = date.today()
    if (c.start is None or c.start <= today) and (c.end is None or c.end >= today):
        return "live"
    return "approved"


def campaign_out(c: m.Campaign) -> CampaignOut:
    period = f"{br_date(c.start) or '[início]'} – {br_date(c.end) or '[fim]'}"
    return CampaignOut(
        id=c.id,
        sponsor=c.brand or c.sponsor.brand or c.sponsor.email,
        slot_name=c.slot.name,
        club=c.slot.artist.name,
        club_slug=c.slot.artist.slug,
        fan_club=c.slot.club.name if c.slot.club else None,
        fan_club_slug=c.slot.club.slug if c.slot.club else None,
        title=c.title,
        text=c.text,
        cta=c.cta,
        url=c.url,
        period=period,
        start=c.start,
        end=c.end,
        art_url=c.art_path or None,
        status=campaign_status(c),
    )


class SponsorOut(Camel):
    id: str
    brand: str
    email: str
    campaigns: int
    status: str


def sponsor_out(s: m.Sponsor) -> SponsorOut:
    return SponsorOut(id=s.id, brand=s.brand or "—", email=s.email, campaigns=len(s.campaigns), status=s.status)


class SponsorInviteIn(Camel):
    email: EmailStr
    brand: str = ""


class SponsorInvited(Camel):
    sponsor: SponsorOut
    temp_password: str | None


# ---------------------------------------------------------------- fã clubes


class PersonOut(Camel):
    name: str
    handle: str = ""


class FanClubOut(Camel):
    id: str
    slug: str
    name: str
    description: str
    city: str
    is_master: bool
    status: str
    members: int
    avatar: str | None = None  # foto de perfil do fã clube
    owner: PersonOut | None = None
    joined: bool = False  # quem está vendo entrou neste fã clube
    my_role: str | None = None  # "owner" | "helper" se quem está vendo é da equipe


def fan_club_out(c: m.FanClub, viewer: m.User | None = None) -> FanClubOut:
    owner = next((st.user for st in c.staff if st.role == m.STAFF_OWNER), None)
    my_role = next((st.role for st in c.staff if viewer and st.user_id == viewer.id), None)
    return FanClubOut(
        id=c.id,
        slug=c.slug,
        name=c.name,
        description=c.description,
        city=c.city,
        is_master=c.is_master,
        status=c.status,
        members=len(c.members),
        avatar=c.avatar_path or None,
        owner=PersonOut(name=owner.name, handle=owner.handle) if owner else None,
        joined=bool(viewer and any(mb.user_id == viewer.id for mb in c.members)),
        my_role=my_role,
    )


class ClubCreateIn(Camel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=80)
    owner_email: EmailStr | None = None  # dono do fã clube (convite)
    owner_name: str = ""


class ClubPatch(Camel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=80)
    status: Literal["active", "setup"] | None = None


class ClubCreated(Camel):
    club: FanClubOut
    invite: InviteOut | None = None


class StaffOut(Camel):
    id: str
    user_id: str
    name: str
    email: str
    role: str  # owner | helper
    role_label: str
    pending: bool  # ainda não trocou a senha provisória


def staff_out(st: m.ClubStaff) -> StaffOut:
    return StaffOut(
        id=st.id,
        user_id=st.user_id,
        name=st.user.name,
        email=st.user.email,
        role=st.role,
        role_label=st.role_label or ("Dono do fã clube" if st.role == m.STAFF_OWNER else "Ajudante"),
        pending=st.user.must_change_password,
    )


class StaffInviteIn(Camel):
    email: EmailStr
    name: str = ""
    role: Literal["owner", "helper"] = "helper"
    role_label: str = Field(default="", max_length=80)


class ClubMemberOut(Camel):
    id: str  # id do usuário
    name: str
    handle: str
    city: str
    since: str
    is_subscriber: bool  # assinante do ambiente do cantor


class ClubPostIn(Camel):
    kind: Literal["galera", "instagram"] = "galera"
    text: str = Field(min_length=1, max_length=2000)
    url: str = Field(default="", max_length=500)
