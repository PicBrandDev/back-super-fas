"""Revenda de ingressos (lado do fã): identidade do vendedor, hub de shows, anúncios, pedidos com escrow e perfil do vendedor.
Contrato completo para o front em docs/revenda-ingressos-frontend.md."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from sqlalchemy import func, select

from .. import models as m
from ..resale import access, identity, listings, orders, payments, trust, views
from ..resale.base import L_LIVE, ResaleError, not_found, utcnow
from ..resale.models import Listing, Order, ResaleEvent
from ..resale.schemas import (
    DisputeIn,
    DisputeOut,
    EligibilityOut,
    EventDetailOut,
    IdentityIn,
    IdentityOut,
    ListingOut,
    ListingsPageOut,
    MyListingOut,
    OrderIn,
    OrderOut,
    ResaleEventOut,
    ReplyIn,
    ReviewIn,
    ReviewOut,
    SellerOut,
    TicketTypeOut,
)
from ..security import DB, CurrentUser, MasterUser
from .fan import FanArtist

router = APIRouter(tags=["Revenda de ingressos"])
PAGE = 20

# ---------------------------------------------------------------- identidade (global, sem ambiente)


def _identity_out(db, user: m.User) -> IdentityOut:
    i = identity.get(db, user)
    if not i:
        return IdentityOut(has_cpf=False, has_phone=False)
    return IdentityOut(has_cpf=True, has_phone=True, cpf_masked=identity.mask_cpf(i.cpf_last2), phone_masked=identity.mask_phone(i.phone_last4), level=i.level)


@router.get("/me/identity", response_model=IdentityOut)
def my_identity(user: CurrentUser, db: DB):
    """CPF e telefone do usuário, só mascarados (os valores completos nunca saem da API)."""
    return _identity_out(db, user)


@router.put("/me/identity", response_model=IdentityOut)
def put_identity(body: IdentityIn, user: CurrentUser, db: DB):
    """Informa CPF e telefone para poder vender. O CPF não troca depois de definido e não pode estar em outra conta."""
    identity.set_identity(db, user, body.cpf, body.phone)
    return _identity_out(db, user)


@router.post("/me/identity/verify/email/start", status_code=501)
def verify_email_start(user: CurrentUser, db: DB):
    identity.verify(db, user, "email")  # ponto de extensão do MFA por e-mail (levanta 501)


@router.post("/me/identity/verify/email/confirm", status_code=501)
def verify_email_confirm(user: CurrentUser, db: DB):
    identity.verify(db, user, "email")


# ---------------------------------------------------------------- hub e anúncios

base = "/artists/{slug}/resale"


@router.get(f"{base}/me/eligibility", response_model=EligibilityOut)
def my_eligibility(artist: FanArtist, user: CurrentUser, db: DB):
    can_buy, can_sell, missing = identity.eligibility(db, artist, user)
    return EligibilityOut(can_buy=can_buy, can_sell=can_sell, missing=missing)


def _event_out(db, e: m.Event) -> ResaleEventOut:
    n, lowest = db.execute(
        select(func.count(Listing.id), func.min(Listing.unit_price_cents)).where(Listing.event_id == e.id, Listing.status == L_LIVE, Listing.qty_available > 0)
    ).one()
    return ResaleEventOut(id=e.id, date=e.date, city=e.city, venue=e.venue, time=e.time, listings_count=n or 0, from_price_cents=lowest)


@router.get(f"{base}/events", response_model=list[ResaleEventOut])
def hub_events(artist: FanArtist, db: DB):
    """Shows com a revenda liberada pelo admin (ticketeira esgotada + revenda aberta), futuros, do mais próximo ao mais distante."""
    q = select(m.Event).join(ResaleEvent, ResaleEvent.event_id == m.Event.id).where(
        m.Event.artist_id == artist.id, ResaleEvent.ticketing_sold_out.is_(True), ResaleEvent.resale_open.is_(True), m.Event.date >= date.today()
    ).order_by(m.Event.date)
    return [_event_out(db, e) for e in db.scalars(q) if access.is_open(db, e)]


@router.get(f"{base}/events/{{event_id}}", response_model=EventDetailOut)
def hub_event(event_id: str, artist: FanArtist, db: DB):
    e = access.get_event(db, artist, event_id)
    access.ensure_open(db, e)
    counts = dict(db.execute(select(Listing.event_ticket_id, func.count(Listing.id)).where(Listing.event_id == e.id, Listing.status == L_LIVE, Listing.qty_available > 0).group_by(Listing.event_ticket_id)).all())
    types = [TicketTypeOut(id=t.id, label=t.label, description=t.description, face_cents=t.price_cents or 0, listings_count=counts.get(t.id, 0)) for t in access.ticket_types(db, e)]
    return EventDetailOut(event=_event_out(db, e), ticket_types=types)


@router.get(f"{base}/events/{{event_id}}/listings", response_model=ListingsPageOut)
def event_listings(event_id: str, artist: FanArtist, db: DB, ticketId: str | None = None, sort: str = "price", page: int = 1):
    """Anúncios no ar do show (com saldo), com o resumo de confiança de cada vendedor."""
    e = access.get_event(db, artist, event_id)
    access.ensure_open(db, e)
    orders.sweep(db, event_id=e.id)  # devolve o saldo de reservas vencidas antes de listar
    q = select(Listing).where(Listing.event_id == e.id, Listing.status == L_LIVE, Listing.qty_available > 0)
    if ticketId:
        q = q.where(Listing.event_ticket_id == ticketId)
    q = q.order_by(Listing.unit_price_cents.asc() if sort == "price" else Listing.created_at.desc(), Listing.id)
    page = max(page, 1)
    rows = list(db.scalars(q.offset((page - 1) * PAGE).limit(PAGE + 1)))
    sellers = trust.sellers(db, artist, [li.seller_id for li in rows[:PAGE]])
    return ListingsPageOut(items=[views.listing_out(li, sellers[li.seller_id]) for li in rows[:PAGE]], page=page, has_more=len(rows) > PAGE)


@router.get(f"{base}/listings/{{listing_id}}", response_model=ListingOut)
def listing_detail(listing_id: str, artist: FanArtist, db: DB):
    li = listings.get_listing(db, artist, listing_id)
    e = db.get(m.Event, li.event_id)
    if li.status != L_LIVE or not access.is_open(db, e):
        raise not_found("Anúncio não encontrado.")
    return views.listing_out(li, trust.sellers(db, artist, [li.seller_id])[li.seller_id])


@router.post(f"{base}/events/{{event_id}}/listings", response_model=MyListingOut, status_code=201)
async def create_listing(
    event_id: str,
    artist: FanArtist,
    user: CurrentUser,
    db: DB,
    ticket_id: Annotated[str, Form(alias="ticketId")],
    qty: Annotated[int, Form()],
    unit_price_cents: Annotated[int, Form(alias="unitPriceCents")],
    codes: Annotated[list[str], Form()],
    proof: Annotated[UploadFile | None, File()] = None,
):
    """Cria o anúncio: N ingressos de um tipo a um preço por ingresso (teto = valor de face), com um código por ingresso e a
    prova (foto, print ou PDF). Entra em análise; o admin aprova ou rejeita antes de ir ao ar."""
    e = access.get_event(db, artist, event_id)
    li = await listings.create(db, artist, user, e, ticket_id, qty, unit_price_cents, codes, proof)
    return views.my_listing_out(db, li)


@router.get(f"{base}/me/listings", response_model=list[MyListingOut])
def my_listings(artist: FanArtist, user: CurrentUser, db: DB):
    orders.sweep(db, user_id=user.id)
    q = select(Listing).where(Listing.artist_id == artist.id, Listing.seller_id == user.id).order_by(Listing.created_at.desc())
    return [views.my_listing_out(db, li) for li in db.scalars(q)]


@router.post(f"{base}/listings/{{listing_id}}/cancel", response_model=MyListingOut)
def cancel_listing(listing_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    return views.my_listing_out(db, listings.cancel(db, user, listings.get_listing(db, artist, listing_id)))


@router.post(f"{base}/listings/{{listing_id}}/resubmit", response_model=MyListingOut)
async def resubmit_listing(
    listing_id: str, artist: FanArtist, user: CurrentUser, db: DB, codes: Annotated[list[str], Form()], proof: Annotated[UploadFile | None, File()] = None
):
    li = await listings.resubmit(db, artist, user, listings.get_listing(db, artist, listing_id), codes, proof)
    return views.my_listing_out(db, li)


# ---------------------------------------------------------------- pedidos


@router.post(f"{base}/listings/{{listing_id}}/orders", response_model=OrderOut, status_code=201)
def reserve(listing_id: str, body: OrderIn, artist: FanArtist, user: CurrentUser, db: DB, idempotency_key: Annotated[str | None, Header()] = None):
    """Reserva a quantidade por 15 minutos. O header Idempotency-Key evita pedido em dobro se a requisição se repetir."""
    if idempotency_key is not None and not 8 <= len(idempotency_key) <= 80:
        raise ResaleError("IDEMPOTENCY_KEY", "A Idempotency-Key precisa ter de 8 a 80 caracteres.")
    o = orders.reserve(db, artist, user, listing_id, body.qty, idempotency_key)
    return views.order_out(db, artist, o, user)


@router.get(f"{base}/me/orders", response_model=list[OrderOut])
def my_orders(artist: FanArtist, user: CurrentUser, db: DB, role: str = "all"):
    orders.sweep(db, user_id=user.id)
    q = select(Order).where(Order.artist_id == artist.id)
    q = q.where(Order.buyer_id == user.id) if role == "buyer" else q.where(Order.seller_id == user.id) if role == "seller" else q.where((Order.buyer_id == user.id) | (Order.seller_id == user.id))
    return views.orders_out(db, artist, list(db.scalars(q.order_by(Order.created_at.desc()).limit(100))), user)


def _mine(db, artist: m.Artist, user: m.User, order_id: str) -> Order:
    o = orders.get_order(db, artist, order_id)
    if user.id not in (o.buyer_id, o.seller_id):
        raise not_found("Pedido não encontrado.")  # não revela pedidos de terceiros
    return o


@router.get(f"{base}/orders/{{order_id}}", response_model=OrderOut)
def order_detail(order_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    o = _mine(db, artist, user, order_id)
    orders.sweep(db, order_id=o.id)
    db.refresh(o)
    return views.order_out(db, artist, o, user)


@router.post(f"{base}/orders/{{order_id}}/pay", response_model=OrderOut)
def pay_order(order_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """Pagamento SIMULADO (só com o provedor falso): retém o valor e abre o prazo de transferência do vendedor."""
    o = orders.pay_fake(db, user, _mine(db, artist, user, order_id))
    return views.order_out(db, artist, o, user)


@router.post(f"{base}/orders/{{order_id}}/cancel", response_model=OrderOut)
def cancel_order(order_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    return views.order_out(db, artist, orders.cancel(db, user, _mine(db, artist, user, order_id)), user)


@router.post(f"{base}/orders/{{order_id}}/transferred", response_model=OrderOut)
def order_transferred(order_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O vendedor avisa que transferiu o ingresso pela ticketeira. Abre o prazo de 48h para o comprador confirmar."""
    return views.order_out(db, artist, orders.mark_transferred(db, user, _mine(db, artist, user, order_id)), user)


@router.post(f"{base}/orders/{{order_id}}/confirm", response_model=OrderOut)
def order_confirm(order_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O comprador confirma o recebimento: o valor é liberado ao vendedor (menos a taxa)."""
    return views.order_out(db, artist, orders.confirm(db, user, _mine(db, artist, user, order_id)), user)


@router.post(f"{base}/orders/{{order_id}}/dispute", response_model=OrderOut)
def order_dispute(order_id: str, body: DisputeIn, artist: FanArtist, user: CurrentUser, db: DB):
    return views.order_out(db, artist, orders.dispute(db, user, _mine(db, artist, user, order_id), body.reason_code, body.description), user)


@router.post(f"{base}/orders/{{order_id}}/dispute/reply", response_model=DisputeOut)
def order_dispute_reply(order_id: str, body: ReplyIn, artist: FanArtist, user: CurrentUser, db: DB):
    return views.dispute_out(orders.dispute_reply(db, user, _mine(db, artist, user, order_id), body.text))


@router.post(f"{base}/orders/{{order_id}}/review", response_model=ReviewOut, status_code=201)
def order_review(order_id: str, body: ReviewIn, artist: FanArtist, user: CurrentUser, db: DB):
    r = orders.review(db, user, _mine(db, artist, user, order_id), body.rating, body.comment)
    return ReviewOut(id=r.id, rating=r.rating, comment=r.comment, created_at="", buyer_name=trust.short_name(user))


# ---------------------------------------------------------------- vendedor


def _known_seller(db, artist: m.Artist, user_id: str) -> None:
    ok = db.scalar(select(Listing.id).where(Listing.artist_id == artist.id, Listing.seller_id == user_id).limit(1)) or db.scalar(
        select(m.Fandom.id).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == user_id)
    )
    if not ok:
        raise not_found("Vendedor não encontrado.")


@router.get(f"{base}/sellers/{{user_id}}", response_model=SellerOut)
def seller_profile(user_id: str, artist: FanArtist, db: DB):
    """Perfil de confiança do vendedor: vendas concluídas, fã clube, nota, tempo na plataforma. Sem CPF, telefone ou e-mail."""
    _known_seller(db, artist, user_id)
    return trust.sellers(db, artist, [user_id])[user_id]


@router.get(f"{base}/sellers/{{user_id}}/reviews", response_model=list[ReviewOut])
def seller_reviews(user_id: str, artist: FanArtist, db: DB, page: int = 1):
    _known_seller(db, artist, user_id)
    return trust.reviews(db, user_id, page)


# ---------------------------------------------------------------- gateway e manutenção (globais)


@router.post("/resale/payments/webhook/{provider}")
async def payment_webhook(provider: str, request: Request, db: DB):
    """Webhook assinado do gateway real. O provedor simulado não aceita webhook."""
    if provider != payments.get_provider().name:
        raise not_found("Provedor desconhecido.")
    data = payments.get_provider().verify_webhook({k.lower(): v for k, v in request.headers.items()}, await request.body())
    if not data:
        raise ResaleError("WEBHOOK_REJECTED", "Webhook não aceito.", 400)
    o = db.get(Order, data["order_id"])
    if not o:
        raise not_found("Pedido não encontrado.")
    orders.confirm_payment(db, o, data.get("ref", ""), data.get("amount_cents"))
    return {"ok": True}


@router.post("/resale/maintenance/sweep")
def maintenance_sweep(master: MasterUser, db: DB):
    """Aplica todos os prazos vencidos (para um cron futuro; a API também aplica os prazos ao ler e agir)."""
    orders.sweep(db)
    return {"ok": True, "at": utcnow().isoformat()}
