"""Tabelas do banco. Os nomes seguem o domínio do front (src/lib/types.ts)."""

import datetime as dt
import secrets
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return secrets.token_hex(5)


def now() -> datetime:
    return datetime.now(timezone.utc)


# Papéis de login
ROLE_FAN = "fan"
ROLE_SPONSOR = "sponsor"
ROLE_ARTIST_ADMIN = "artist_admin"
ROLE_MASTER = "master"
ROLES = (ROLE_FAN, ROLE_SPONSOR, ROLE_ARTIST_ADMIN, ROLE_MASTER)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    handle: Mapped[str] = mapped_column(String(60), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    role: Mapped[str] = mapped_column(String(20), index=True)
    # Conta criada por convite com senha provisória (ainda não trocou).
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    sponsor_id: Mapped[str | None] = mapped_column(ForeignKey("sponsors.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    sponsor: Mapped["Sponsor | None"] = relationship(back_populates="users")
    admin_of: Mapped[list["ArtistAdmin"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    fandoms: Mapped[list["Fandom"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    fan_club_name: Mapped[str] = mapped_column(String(120), default="")
    instagram: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="setup")  # active | setup
    theme: Mapped[dict] = mapped_column(JSON)
    member_price_cents: Mapped[int] = mapped_column(Integer, default=1690)
    brand_color: Mapped[str] = mapped_column(String(20), default="#2F5BD3")
    modules: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    admins: Mapped[list["ArtistAdmin"]] = relationship(back_populates="artist", cascade="all, delete-orphan")
    fandoms: Mapped[list["Fandom"]] = relationship(back_populates="artist", cascade="all, delete-orphan")
    ad_slots: Mapped[list["AdSlot"]] = relationship(back_populates="artist", cascade="all, delete-orphan")


class ArtistAdmin(Base):
    """Administrador de um fã clube (até 10 por artista)."""

    __tablename__ = "artist_admins"
    __table_args__ = (UniqueConstraint("artist_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_label: Mapped[str] = mapped_column(String(80), default="Administrador")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    artist: Mapped[Artist] = relationship(back_populates="admins")
    user: Mapped[User] = relationship(back_populates="admin_of")


class Fandom(Base):
    """Relação fã ↔ fã clube: pontos, giros e a assinatura de membro."""

    __tablename__ = "fandoms"
    __table_args__ = (UniqueConstraint("artist_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    luck_points: Mapped[int] = mapped_column(Integer, default=0)
    spins: Mapped[int] = mapped_column(Integer, default=3)
    member_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # active | pending | canceled
    member_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment: Mapped[str] = mapped_column(String(20), default="Pix")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    artist: Mapped[Artist] = relationship(back_populates="fandoms")
    user: Mapped[User] = relationship(back_populates="fandoms")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # drop | galera | instagram
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    quote: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    author: Mapped[User | None] = relationship()


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    city: Mapped[str] = mapped_column(String(120))
    venue: Mapped[str] = mapped_column(String(160), default="")
    time: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    doors_open: Mapped[str] = mapped_column(String(20), default="")
    age_rating: Mapped[str] = mapped_column(String(20), default="")
    lineup: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="soon")  # on_sale | last_batches | soon

    vendors: Mapped[list["Vendor"]] = relationship(cascade="all, delete-orphan")
    gifts: Mapped[list["Gift"]] = relationship(cascade="all, delete-orphan")


class Vendor(Base):
    """Onde comprar (ingresso, pacote, excursão) de um evento."""

    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(160), default="")
    tag: Mapped[str] = mapped_column(String(20), default="Oficial")  # Oficial | Pacote | Excursão
    price_label: Mapped[str] = mapped_column(String(80), default="")
    url: Mapped[str] = mapped_column(String(500), default="#")
    position: Mapped[int] = mapped_column(Integer, default=0)


class Gift(Base):
    """Brinde da sorte do evento (antes ou depois do show)."""

    __tablename__ = "gifts"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phase: Mapped[str] = mapped_column(String(10), default="before")  # before | after
    qty_label: Mapped[str] = mapped_column(String(40), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


class EventEntry(Base):
    """Fã participando da sorte de um evento."""

    __tablename__ = "event_entries"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Prize(Base):
    """Fatia da roleta do PicKap."""

    __tablename__ = "prizes"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(60))
    is_retry: Mapped[bool] = mapped_column(Boolean, default=False)
    points: Mapped[int] = mapped_column(Integer, default=0)  # pontos da sorte que a fatia dá
    position: Mapped[int] = mapped_column(Integer, default=0)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20), default="roupas")  # roupas | acessorios | musica
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="#E0A526")
    position: Mapped[int] = mapped_column(Integer, default=0)


class Track(Base):
    """Prévia do Drops Hits."""

    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    meta: Mapped[str] = mapped_column(String(160), default="")
    release_label: Mapped[str] = mapped_column(String(60), default="")
    duration_sec: Mapped[int] = mapped_column(Integer, default=30)
    votes: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)


class MemberPerk(Base):
    __tablename__ = "member_perks"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    sub: Mapped[str] = mapped_column(String(200), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


class AdSlot(Base):
    """Vitrine de anúncio dentro de um fã clube."""

    __tablename__ = "ad_slots"
    __table_args__ = (UniqueConstraint("artist_id", "key"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(30))  # home | mural | evento | pickap | loja | drops
    name: Mapped[str] = mapped_column(String(120))
    where: Mapped[str] = mapped_column(String(200), default="")
    format: Mapped[str] = mapped_column(String(160), default="")
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)  # por semana
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    diagram_top: Mapped[int] = mapped_column(Integer, default=20)
    diagram_height: Mapped[int] = mapped_column(Integer, default=16)
    position: Mapped[int] = mapped_column(Integer, default=0)

    artist: Mapped[Artist] = relationship(back_populates="ad_slots")


class Sponsor(Base):
    __tablename__ = "sponsors"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    brand: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="invited")  # active | invited
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    users: Mapped[list[User]] = relationship(back_populates="sponsor")
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="sponsor", cascade="all, delete-orphan")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    sponsor_id: Mapped[str] = mapped_column(ForeignKey("sponsors.id", ondelete="CASCADE"), index=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey("ad_slots.id", ondelete="CASCADE"), index=True)
    brand: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(String(60), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    art_path: Mapped[str] = mapped_column(String(255), default="")
    start: Mapped[date | None] = mapped_column(Date, nullable=True)
    end: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    sponsor: Mapped[Sponsor] = relationship(back_populates="campaigns")
    slot: Mapped[AdSlot] = relationship()
