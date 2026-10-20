"""Admin do fã clube: conteúdo (CRUD), membros e equipe.

Todas as rotas exigem ser admin daquele fã clube (ou o admin master).
O conteúdo segue o padrão:
    GET    /artists/{slug}/manage/{recurso}
    POST   /artists/{slug}/manage/{recurso}
    PATCH  /artists/{slug}/manage/{recurso}/{id}
    DELETE /artists/{slug}/manage/{recurso}/{id}
"""

from datetime import date
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import Field, create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import AdminInviteIn, Camel, ClubAdminOut, InviteOut, MemberOut, br_date
from ..security import DB, ManagedArtist, hash_password, temp_password

router = APIRouter(tags=["Admin do fã clube"])

MAX_ADMINS = 10


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


class VendorIn(Camel):
    event_id: str
    name: str = Field(min_length=1, max_length=120)
    type: str = ""
    tag: Literal["Oficial", "Pacote", "Excursão"] = "Oficial"
    price_label: str = ""
    url: str = "#"
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


def _post_defaults(db: Session, artist: m.Artist, data: dict[str, Any]) -> None:
    if "kind" in data:
        data["official"] = data["kind"] == "drop"


RESOURCES: list[tuple[str, type, type[Camel], Any, Callable | None]] = [
    ("events", m.Event, EventIn, m.Event.date, None),
    ("vendors", m.Vendor, VendorIn, m.Vendor.position, _check_event),
    ("gifts", m.Gift, GiftIn, m.Gift.position, _check_event),
    ("posts", m.Post, PostIn, m.Post.created_at.desc(), _post_defaults),
    ("prizes", m.Prize, PrizeIn, m.Prize.position, None),
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
        for f, v in data.items():
            setattr(obj, f, v)
        db.commit()
        db.refresh(obj)
        return to_out(obj)

    @router.delete(f"{path}/{{item_id}}", status_code=204, tags=tag, name=f"delete_{name}")
    def delete_item(item_id: str, artist: ManagedArtist, db: DB):
        db.delete(get_obj(db, artist, item_id))
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


# ---------------------------------------------------------------- equipe


def club_admin_out(a: m.ArtistAdmin) -> ClubAdminOut:
    return ClubAdminOut(
        id=a.id,
        user_id=a.user_id,
        name=a.user.name,
        email=a.user.email,
        role=a.role_label,
        pending=a.user.must_change_password,
    )


def add_club_admin(db: Session, artist: m.Artist, email: str, name: str = "", role: str = "Administrador") -> InviteOut:
    """Cria (ou vincula) a conta de um admin do fã clube. Devolve a senha provisória quando cria."""
    email = email.lower()
    if len(artist.admins) >= MAX_ADMINS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"O fã clube já tem {MAX_ADMINS} administradores.")
    user = db.scalar(select(m.User).where(m.User.email == email))
    password = None
    if user:
        if user.role != m.ROLE_ARTIST_ADMIN:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{email} já tem uma conta de outro tipo.")
        if any(a.user_id == user.id for a in artist.admins):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{email} já administra este fã clube.")
    else:
        password = temp_password()
        user = m.User(
            email=email,
            name=name.strip() or email.split("@")[0],
            password_hash=hash_password(password),
            role=m.ROLE_ARTIST_ADMIN,
            must_change_password=True,
        )
        db.add(user)
    db.add(m.ArtistAdmin(artist=artist, user=user, role_label=role or "Administrador"))
    db.flush()
    return InviteOut(email=email, temp_password=password)


@router.get("/artists/{slug}/admins", response_model=list[ClubAdminOut])
def list_admins(artist: ManagedArtist):
    return [club_admin_out(a) for a in sorted(artist.admins, key=lambda a: a.created_at)]


@router.post("/artists/{slug}/admins", response_model=InviteOut, status_code=201)
def invite_admin(body: AdminInviteIn, artist: ManagedArtist, db: DB):
    out = add_club_admin(db, artist, body.email, body.name, body.role)
    db.commit()
    return out


@router.delete("/artists/{slug}/admins/{admin_id}", status_code=204)
def remove_admin(admin_id: str, artist: ManagedArtist, db: DB):
    a = db.get(m.ArtistAdmin, admin_id)
    if not a or a.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Administrador não encontrado.")
    db.delete(a)
    db.commit()
