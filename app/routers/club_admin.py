"""Administração do ambiente do cantor: conteúdo oficial (CRUD) e assinantes.

Todas as rotas exigem ser da equipe do fã clube master daquele cantor (ou o admin da plataforma).
O PicKup, o mural da galera e a equipe de cada fã clube ficam em clubs.py.
O conteúdo segue o padrão:
    GET    /artists/{slug}/manage/{recurso}
    POST   /artists/{slug}/manage/{recurso}
    PATCH  /artists/{slug}/manage/{recurso}/{id}
    DELETE /artists/{slug}/manage/{recurso}/{id}
"""

from datetime import date, datetime, timezone
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import Field, create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..resale.guards import ensure_deletable, ensure_editable
from ..schemas import Camel, MemberOut, RewardOut, br_date
from ..security import DB, ManagedArtist

router = APIRouter(tags=["Administração do ambiente"])


# ---------------------------------------------------------------- formatos de entrada do conteúdo


class EventIn(Camel):
    date: date
    city: str = Field(min_length=1, max_length=120)
    venue: str = ""
    time: str = ""
    address: str = ""
    doors_open: str = ""
    age_rating: str = ""
    lineup: str = ""
    status: Literal["on_sale", "last_batches", "soon"] = "soon"
    ticketing_name: str = Field(default="", max_length=60)
    ticketing_url: str = Field(default="", max_length=500)


class VendorIn(Camel):
    event_id: str
    name: str = Field(min_length=1, max_length=120)
    type: str = ""
    tag: Literal["Oficial", "Pacote", "Excursão"] = "Oficial"
    price_label: str = ""
    url: str = "#"
    position: int = 0


class TicketIn(Camel):
    event_id: str
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=200)
    price_cents: int = Field(default=0, ge=0)
    sold_out: bool = False
    position: int = 0


class AgencyIn(Camel):
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default="", max_length=160)
    url: str = Field(default="", max_length=500)
    active: bool = True


class PackageItemIn(Camel):
    kind: Literal["ticket", "transfer", "seal", "photo"] = "ticket"  # só ingresso | + transfer | + selo no app ("photo" é legado)
    label: str = Field(min_length=1, max_length=120)  # ex.: "Pista", "Camarote", "Ônibus ida e volta"
    price_cents: int = Field(default=0, ge=0)
    sold_out: bool = False


class AddonIn(Camel):
    key: Literal["jantar", "camarim", "pre", "after", "hotel"]
    price_cents: int = Field(default=0, ge=0)
    sold_out: bool = False


class CouponIn(Camel):
    code: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["percent", "fixed"] = "percent"
    value: int = Field(ge=1)  # % (1 a 100) ou centavos
    active: bool = True
    expires_on: date | None = None
    max_uses: int = Field(default=0, ge=0)  # 0 = ilimitado
    source: str = Field(default="", max_length=80)


class PackageIn(Camel):
    event_id: str
    agency_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    transfer_details: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=500)
    items: list[PackageItemIn] = Field(default_factory=list, max_length=30)
    addons: list[AddonIn] = Field(default_factory=list, max_length=10)
    active: bool = True
    position: int = 0


class GiftIn(Camel):
    event_id: str
    name: str = Field(min_length=1, max_length=120)
    phase: Literal["before", "after"] = "before"
    qty_label: str = ""
    position: int = 0


class PostIn(Camel):
    kind: Literal["drop", "galera", "instagram"] = "drop"
    text: str = Field(min_length=1, max_length=4000)
    has_image: bool = False
    quote: str = ""
    url: str = ""
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    reposts: int = Field(default=0, ge=0)


class PrizeIn(Camel):
    label: str = Field(min_length=1, max_length=60)
    is_retry: bool = False
    points: int = Field(default=0, ge=0)
    position: int = 0
    kind: Literal["", "none", "retry", "coupon", "ticket", "pickup"] = ""
    percent: int = Field(default=0, ge=0, le=100)
    instructions: str = Field(default="", max_length=200)
    stock: int | None = Field(default=None, ge=0)  # unidades para dar (vazio = ilimitado)


class ProductIn(Camel):
    name: str = Field(min_length=1, max_length=120)
    category: Literal["roupas", "acessorios", "musica"] = "roupas"
    price_cents: int | None = Field(default=None, ge=0)
    color: str = "#E0A526"
    position: int = 0


class TrackIn(Camel):
    title: str = Field(min_length=1, max_length=160)
    meta: str = ""
    release_label: str = ""
    duration_sec: int = Field(default=30, ge=1, le=600)
    votes: int = Field(default=0, ge=0)
    views: int = Field(default=0, ge=0)
    position: int = 0


class PerkIn(Camel):
    title: str = Field(min_length=1, max_length=120)
    sub: str = ""
    position: int = 0


def _check_event(db: Session, artist: m.Artist, data: dict[str, Any]) -> None:
    event_id = data.get("event_id")
    if event_id is None:
        return
    e = db.get(m.Event, event_id)
    if not e or e.artist_id != artist.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Evento inválido para este fã clube.")


def _check_package(db: Session, artist: m.Artist, data: dict[str, Any]) -> None:
    _check_event(db, artist, data)
    agency_id = data.get("agency_id")
    if agency_id is not None:
        a = db.get(m.Agency, agency_id)
        if not a or a.artist_id != artist.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Agência inválida para este ambiente.")
        # Cada show tem uma única agência: todos os pacotes dele são dela.
        event_id = data.get("event_id")
        if event_id:
            other = db.scalar(select(m.EventPackage).where(m.EventPackage.event_id == event_id, m.EventPackage.agency_id != agency_id))
            if other:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Este show já é da agência {other.agency.name}. Todos os pacotes dele precisam ser dessa agência.")


def _check_coupon(db: Session, artist: m.Artist, data: dict[str, Any]) -> None:
    if "code" in data:
        data["code"] = data["code"].strip().upper()
    if data.get("kind") == "percent" and data.get("value", 1) > 100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O desconto percentual vai de 1 a 100.")


def _post_defaults(db: Session, artist: m.Artist, data: dict[str, Any]) -> None:
    # Posts criados pela administração do ambiente são oficiais (sem fã clube).
    if "kind" in data:
        data["official"] = data["kind"] == "drop"


RESOURCES: list[tuple[str, type, type[Camel], Any, Callable | None]] = [
    ("events", m.Event, EventIn, m.Event.date, None),
    ("vendors", m.Vendor, VendorIn, m.Vendor.position, _check_event),
    ("gifts", m.Gift, GiftIn, m.Gift.position, _check_event),
    ("tickets", m.EventTicket, TicketIn, m.EventTicket.position, _check_event),
    ("agencies", m.Agency, AgencyIn, m.Agency.name, None),
    ("packages", m.EventPackage, PackageIn, m.EventPackage.position, _check_package),
    ("coupons", m.Coupon, CouponIn, m.Coupon.code, _check_coupon),
    ("posts", m.Post, PostIn, m.Post.created_at.desc(), _post_defaults),
    ("products", m.Product, ProductIn, m.Product.position, None),
    ("tracks", m.Track, TrackIn, m.Track.position, None),
    ("perks", m.MemberPerk, PerkIn, m.MemberPerk.position, None),
]


def _register(name: str, model: type, In: type[Camel], order_by: Any, hook: Callable | None) -> None:
    Out = create_model(f"{In.__name__[:-2]}Admin", __base__=In, id=(str, ...))
    Patch = create_model(
        f"{In.__name__[:-2]}Patch",
        __base__=Camel,
        **{f: (Optional[info.annotation], None) for f, info in In.model_fields.items()},  # type: ignore[valid-type]
    )
    fields = list(In.model_fields)

    def to_out(obj: Any) -> Any:
        return Out(id=obj.id, **{f: getattr(obj, f) for f in fields})

    def get_obj(db: Session, artist: m.Artist, item_id: str) -> Any:
        obj = db.get(model, item_id)
        if not obj or obj.artist_id != artist.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item não encontrado.")
        return obj

    path = f"/artists/{{slug}}/manage/{name}"
    tag = [f"Conteúdo · {name}"]

    @router.get(path, response_model=list[Out], tags=tag, name=f"list_{name}")
    def list_items(artist: ManagedArtist, db: DB, event_id: str | None = None):
        q = select(model).where(model.artist_id == artist.id)
        if event_id and hasattr(model, "event_id"):
            q = q.where(model.event_id == event_id)
        return [to_out(o) for o in db.scalars(q.order_by(order_by))]

    @router.post(path, response_model=Out, status_code=201, tags=tag, name=f"create_{name}")
    def create_item(body: In, artist: ManagedArtist, db: DB):  # type: ignore[valid-type]
        data = body.model_dump()
        if hook:
            hook(db, artist, data)
        obj = model(artist_id=artist.id, **data)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return to_out(obj)

    @router.patch(f"{path}/{{item_id}}", response_model=Out, tags=tag, name=f"update_{name}")
    def update_item(item_id: str, body: Patch, artist: ManagedArtist, db: DB):  # type: ignore[valid-type]
        obj = get_obj(db, artist, item_id)
        data = body.model_dump(exclude_unset=True)
        # Campos obrigatórios não podem virar nulo.
        for f, v in list(data.items()):
            if v is None and In.model_fields[f].is_required():
                data.pop(f)
        if hook:
            hook(db, artist, data)
        ensure_editable(db, obj, data)  # revenda: não muda data/horário do show com compra em andamento
        for f, v in data.items():
            setattr(obj, f, v)
        db.commit()
        db.refresh(obj)
        return to_out(obj)

    @router.delete(f"{path}/{{item_id}}", status_code=204, tags=tag, name=f"delete_{name}")
    def delete_item(item_id: str, artist: ManagedArtist, db: DB):
        obj = get_obj(db, artist, item_id)
        ensure_deletable(db, obj)  # revenda de ingressos: não apaga show/ingresso que sustenta dinheiro retido
        db.delete(obj)
        db.commit()


for _r in RESOURCES:
    _register(*_r)


# ---------------------------------------------------------------- membros


def _member(db: Session, artist: m.Artist, member_id: str) -> m.Fandom:
    f = db.get(m.Fandom, member_id)
    if not f or f.artist_id != artist.id or f.member_status is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membro não encontrado.")
    return f


@router.get("/artists/{slug}/members", response_model=list[MemberOut])
def list_members(artist: ManagedArtist, db: DB):
    q = (
        select(m.Fandom)
        .where(m.Fandom.artist_id == artist.id, m.Fandom.member_status.is_not(None))
        .order_by(m.Fandom.member_since.desc())
    )
    return [
        MemberOut(
            id=f.id,
            name=f.user.name,
            handle=f.user.handle or f.user.email,
            status=f.member_status or "pending",
            since=br_date(f.member_since),
            payment=f.payment,
            points=f.luck_points,
            city=f.user.city,
        )
        for f in db.scalars(q)
    ]


@router.post("/artists/{slug}/members/{member_id}/charge")
def charge_member(member_id: str, artist: ManagedArtist, db: DB):
    _member(db, artist, member_id)
    # Ainda não há gateway de pagamento: só confirma o pedido.
    return {"ok": True}


@router.post("/artists/{slug}/members/{member_id}/cancel")
def cancel_member(member_id: str, artist: ManagedArtist, db: DB):
    f = _member(db, artist, member_id)
    f.member_status = "canceled"
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- brindes da roleta (retirada)


@router.post("/artists/{slug}/manage/rewards/{code}/redeem", response_model=RewardOut, tags=["Brindes da roleta"])
def redeem_reward(code: str, artist: ManagedArtist, db: DB):
    """A equipe dá baixa no brinde quando o fã retira (lojinha ou bilheteria) com o código."""
    from .. import rewards

    r = db.scalar(select(m.Reward).where(m.Reward.artist_id == artist.id, m.Reward.code == code.strip().upper()))
    if not r or r.kind == "coupon":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brinde não encontrado para retirada.")
    if r.redeemed_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este brinde já foi retirado.")
    if rewards.status_of(db, r) == "expired":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O prazo para retirar este brinde acabou.")
    r.redeemed_at = datetime.now(timezone.utc)
    db.commit()
    return rewards.out(db, r)
