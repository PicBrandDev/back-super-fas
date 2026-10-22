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
    avatar_path: Mapped[str] = mapped_column(String(255), default="")  # foto de perfil (ex.: /uploads/abc.jpg)
    city: Mapped[str] = mapped_column(String(80), default="")
    # Endereço do fã (cadastro): de onde são os assinantes.
    zip_code: Mapped[str] = mapped_column(String(9), default="")
    street: Mapped[str] = mapped_column(String(160), default="")
    number: Mapped[str] = mapped_column(String(20), default="")
    complement: Mapped[str] = mapped_column(String(80), default="")
    neighborhood: Mapped[str] = mapped_column(String(80), default="")
    state: Mapped[str] = mapped_column(String(2), default="", index=True)  # UF
    role: Mapped[str] = mapped_column(String(20), index=True)
    # Conta criada por convite com senha provisória (ainda não trocou).
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    sponsor_id: Mapped[str | None] = mapped_column(ForeignKey("sponsors.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    sponsor: Mapped["Sponsor | None"] = relationship(back_populates="users")
    admin_of: Mapped[list["ArtistAdmin"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    fandoms: Mapped[list["Fandom"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    staff_of: Mapped[list["ClubStaff"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    clubs: Mapped[list["ClubMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


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
    clubs: Mapped[list["FanClub"]] = relationship(
        back_populates="artist", cascade="all, delete-orphan", order_by="FanClub.position"
    )
    fandoms: Mapped[list["Fandom"]] = relationship(back_populates="artist", cascade="all, delete-orphan")
    ad_slots: Mapped[list["AdSlot"]] = relationship(back_populates="artist", cascade="all, delete-orphan")


class ArtistAdmin(Base):
    """LEGADO: equipe por artista (antes dos fã clubes). Só é lida pela migração em migrations.py."""

    __tablename__ = "artist_admins"
    __table_args__ = (UniqueConstraint("artist_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_label: Mapped[str] = mapped_column(String(80), default="Administrador")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    artist: Mapped[Artist] = relationship(back_populates="admins")
    user: Mapped[User] = relationship(back_populates="admin_of")


# Equipe de um fã clube
STAFF_OWNER = "owner"
STAFF_HELPER = "helper"


class FanClub(Base):
    """Fã clube dentro do ambiente de um cantor (1 master + quantos quiser).

    A equipe do fã clube master é a administração do ambiente do cantor.
    """

    __tablename__ = "fan_clubs"
    __table_args__ = (UniqueConstraint("artist_id", "slug"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(300), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | setup
    position: Mapped[int] = mapped_column(Integer, default=0)
    avatar_path: Mapped[str] = mapped_column(String(255), default="")  # foto de perfil (ex.: /uploads/abc.jpg)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    artist: Mapped["Artist"] = relationship(back_populates="clubs")
    staff: Mapped[list["ClubStaff"]] = relationship(back_populates="club", cascade="all, delete-orphan")
    members: Mapped[list["ClubMember"]] = relationship(back_populates="club", cascade="all, delete-orphan")


class ClubStaff(Base):
    """Dono ou ajudante de um fã clube."""

    __tablename__ = "club_staff"
    __table_args__ = (UniqueConstraint("club_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    club_id: Mapped[str] = mapped_column(ForeignKey("fan_clubs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default=STAFF_HELPER)  # owner | helper
    role_label: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    club: Mapped[FanClub] = relationship(back_populates="staff")
    user: Mapped["User"] = relationship(back_populates="staff_of")


class ClubMember(Base):
    """Fã que entrou num fã clube (grátis; o fã pode estar em vários)."""

    __tablename__ = "club_members"
    __table_args__ = (UniqueConstraint("club_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    club_id: Mapped[str] = mapped_column(ForeignKey("fan_clubs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    club: Mapped[FanClub] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="clubs")


class Fandom(Base):
    """Relação fã ↔ fã clube: pontos, giros e a assinatura de membro."""

    __tablename__ = "fandoms"
    __table_args__ = (UniqueConstraint("artist_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    luck_points: Mapped[int] = mapped_column(Integer, default=0)
    spins: Mapped[int] = mapped_column(Integer, default=3)
    share_code: Mapped[str] = mapped_column(String(12), default="", index=True)  # código do fã nas legendas (ex.: FS-7K2QM)
    member_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # active | pending | canceled
    member_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment: Mapped[str] = mapped_column(String(20), default="Pix")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    artist: Mapped[Artist] = relationship(back_populates="fandoms")
    user: Mapped[User] = relationship(back_populates="fandoms")


class InstagramShare(Base):
    """Compartilhamento de um post no Instagram do fã (Fã Super). Só `verified` pontua no ranking."""

    __tablename__ = "instagram_shares"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[str | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"), nullable=True)
    track_id: Mapped[str | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"), nullable=True)  # compartilhou um Drop (faixa)
    status: Mapped[str] = mapped_column(String(10), default="started")  # started | claimed (o fã disse que postou) | verified
    media_id: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)  # id do post no Instagram
    permalink: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventPhoto(Base):
    """Foto oficial de um show. Os rostos dela ficam indexados no AWS Rekognition para o Photo Finder."""

    __tablename__ = "event_photos"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(255))  # ex.: /uploads/abc.jpg
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    face_ids: Mapped[list] = mapped_column(JSON, default=list)  # rostos desta foto no Rekognition
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TicketPurchase(Base):
    """Ingresso que o fã comprou (hoje simulado: o pagamento acontece fora do app)."""

    __tablename__ = "ticket_purchases"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    package_name: Mapped[str] = mapped_column(String(120), default="")
    agency_name: Mapped[str] = mapped_column(String(120), default="")
    label: Mapped[str] = mapped_column(String(160))  # ex.: "Pista + transfer + selo"
    kind: Mapped[str] = mapped_column(String(10), default="ticket")  # ticket | transfer | seal | photo
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    event: Mapped["Event"] = relationship()


class SpinCredit(Base):
    """Um giro da roleta (PicKap) do fã, com o motivo de ele existir (compra de ingresso, boas-vindas...)."""

    __tablename__ = "spin_credits"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(200))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prize_label: Mapped[str] = mapped_column(String(80), default="")  # o que saiu quando foi usado
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # drop | galera | instagram
    # Fã clube do post (galera/instagram). Vazio = oficial do ambiente (Drop News).
    club_id: Mapped[str | None] = mapped_column(ForeignKey("fan_clubs.id", ondelete="CASCADE"), nullable=True, index=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    quote: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    image_path: Mapped[str] = mapped_column(String(255), default="")  # foto enviada (ex.: /uploads/abc.jpg)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    author: Mapped[User | None] = relationship()
    club: Mapped["FanClub | None"] = relationship()
    replies: Mapped[list["PostComment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="PostComment.created_at"
    )


class PostComment(Base):
    """Comentário de um fã num post."""

    __tablename__ = "post_comments"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    post: Mapped[Post] = relationship(back_populates="replies")
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
    ticketing_name: Mapped[str] = mapped_column(String(60), default="")  # ticketeira oficial (ex.: Sympla)
    ticketing_url: Mapped[str] = mapped_column(String(500), default="")  # link de compra na ticketeira

    vendors: Mapped[list["Vendor"]] = relationship(cascade="all, delete-orphan")
    gifts: Mapped[list["Gift"]] = relationship(cascade="all, delete-orphan")
    packages: Mapped[list["EventPackage"]] = relationship(cascade="all, delete-orphan", order_by="EventPackage.position")
    tickets: Mapped[list["EventTicket"]] = relationship(cascade="all, delete-orphan", order_by="EventTicket.position")


class EventTicket(Base):
    """Tipo de ingresso avulso do show (vendido na ticketeira): Pista, Camarote... com o preço de cada um."""

    __tablename__ = "event_tickets"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(200), default="")
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    sold_out: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)


class Agency(Base):
    """Agência parceira do artista: distribui pacotes (ingressos e transfer) dos shows."""

    __tablename__ = "agencies"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    contact: Mapped[str] = mapped_column(String(160), default="")  # WhatsApp ou e-mail
    url: Mapped[str] = mapped_column(String(500), default="")  # site da agência
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    packages: Mapped[list["EventPackage"]] = relationship(back_populates="agency", cascade="all, delete-orphan")


class EventPackage(Base):
    """Pacote de uma agência para um show: vários tipos de ingresso (com preço) e opções de transfer."""

    __tablename__ = "event_packages"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    agency_id: Mapped[str] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(300), default="")
    transfer_details: Mapped[str] = mapped_column(String(300), default="")  # saída, horário, volta
    url: Mapped[str] = mapped_column(String(500), default="")  # link de venda do pacote
    # [{"kind": "ticket" (só ingresso) | "transfer" (ingresso + transfer) | "seal" (+ selo no app) | "photo" (+ selo + Photo Finder), "label": "Pista", "price_cents": 18000, "sold_out": false}]
    items: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    agency: Mapped[Agency] = relationship(back_populates="packages")


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
    """Fatia da roleta do PicKap (cada fã clube tem a sua roleta)."""

    __tablename__ = "prizes"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    club_id: Mapped[str | None] = mapped_column(ForeignKey("fan_clubs.id", ondelete="CASCADE"), nullable=True, index=True)
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


class ProductPurchase(Base):
    """Produto da loja que o fã comprou (hoje simulado: o pagamento acontece fora do app)."""

    __tablename__ = "product_purchases"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20), default="roupas")
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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
    """Vitrine de anúncio: do ambiente do cantor (club_id vazio) ou de um fã clube."""

    __tablename__ = "ad_slots"
    __table_args__ = (UniqueConstraint("artist_id", "key"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    club_id: Mapped[str | None] = mapped_column(ForeignKey("fan_clubs.id", ondelete="CASCADE"), nullable=True, index=True)
    # Ambiente: home | mural | evento | pickap | loja | drops. Fã clube: "{slug do clube}.home" etc.
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    where: Mapped[str] = mapped_column(String(200), default="")
    format: Mapped[str] = mapped_column(String(160), default="")
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)  # por semana
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    diagram_top: Mapped[int] = mapped_column(Integer, default=20)
    diagram_height: Mapped[int] = mapped_column(Integer, default=16)
    position: Mapped[int] = mapped_column(Integer, default=0)

    artist: Mapped[Artist] = relationship(back_populates="ad_slots")
    club: Mapped["FanClub | None"] = relationship()


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
