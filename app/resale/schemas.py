"""Schemas de entrada e saída da revenda (camelCase). Saídas são sempre explícitas: nunca devolvem o modelo do banco
nem CPF, telefone ou e-mail de ninguém."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from ..schemas import Camel

# ---------------------------------------------------------------- identidade


class IdentityIn(Camel):
    cpf: str = Field(min_length=11, max_length=14)
    phone: str = Field(min_length=10, max_length=20)


class IdentityOut(Camel):
    has_cpf: bool
    has_phone: bool
    cpf_masked: str = ""
    phone_masked: str = ""
    level: str = "none"  # none | declared | verified


class EligibilityOut(Camel):
    can_buy: bool
    can_sell: bool
    missing: list[str]  # role | fandom | address | cpf | phone


# ---------------------------------------------------------------- confiança do vendedor


class ClubPositionOut(Camel):
    name: str
    slug: str
    position: Literal["owner", "helper", "member"]


class SellerOut(Camel):
    user_id: str
    handle: str
    display_name: str
    avatar: str | None = None
    member_since: str
    completed_sales: int
    avg_rating: float | None = None
    rating_count: int
    clubs: list[ClubPositionOut]
    is_member: bool  # assinante (selo de membro)
    identity_level: str  # none | declared | verified
    identity_verified: bool


class ReviewOut(Camel):
    id: str
    rating: int
    comment: str
    created_at: str
    buyer_name: str


class ReviewIn(Camel):
    rating: int
    comment: str = Field(default="", max_length=500)


# ---------------------------------------------------------------- hub, anúncios


class ResaleEventOut(Camel):
    id: str
    date: date
    city: str
    venue: str
    time: str
    listings_count: int
    from_price_cents: int | None = None


class TicketTypeOut(Camel):
    id: str
    label: str
    description: str
    face_cents: int  # o teto de preço por ingresso
    listings_count: int


class EventDetailOut(Camel):
    event: ResaleEventOut
    ticket_types: list[TicketTypeOut]


class ListingOut(Camel):
    id: str
    event_id: str
    ticket_id: str | None
    ticket_label: str
    face_cents: int
    qty_total: int
    qty_available: int
    unit_price_cents: int
    created_at: str
    seller: SellerOut


class ListingsPageOut(Camel):
    items: list[ListingOut]
    page: int
    has_more: bool


class MyListingOut(Camel):
    id: str
    event_id: str
    event_city: str
    event_date: date
    ticket_label: str
    face_cents: int
    qty_total: int
    qty_available: int
    unit_price_cents: int
    status: str  # pending_review | live | rejected | cancelled | closed
    review_reason: str
    attempts: int
    can_resubmit: bool
    can_cancel: bool
    active_orders: int
    created_at: str


# ---------------------------------------------------------------- pedidos


class OrderIn(Camel):
    qty: int = Field(ge=1, le=10)
    # e-mail da conta do comprador na ticketeira (para onde o vendedor transfere); vazio = o e-mail do cadastro
    transfer_to: str = Field(default="", max_length=160)


class DisputeIn(Camel):
    reason_code: Literal["not_received", "invalid_ticket", "wrong_type", "other"]
    description: str = Field(default="", max_length=1000)


class ReplyIn(Camel):
    text: str = Field(min_length=1, max_length=1000)


class DisputeOut(Camel):
    id: str
    order_id: str
    status: str
    reason_code: str
    description: str
    seller_reply: str
    resolution: str
    decision_note: str
    created_at: str


class OrderOut(Camel):
    id: str
    status: str  # reserved | awaiting_transfer | transferred | completed | disputed | refunded | expired | cancelled
    role: Literal["buyer", "seller"]
    listing_id: str
    event_id: str
    event_city: str
    event_date: date
    event_venue: str
    ticket_label: str
    qty: int
    unit_price_cents: int
    gross_cents: int  # o que o comprador paga
    fee_cents: int  # taxa da plataforma (descontada do vendedor)
    seller_net_cents: int  # o que o vendedor recebe
    reserved_until: datetime | None
    paid_at: datetime | None
    transfer_deadline: datetime | None
    transferred_at: datetime | None
    confirm_deadline: datetime | None
    closed_at: datetime | None
    close_reason: str
    counterparty: SellerOut | None = None  # comprador vê o vendedor completo
    buyer_handle: str | None = None  # vendedor vê só o handle e o nome abreviado do comprador
    buyer_name: str | None = None
    dispute: DisputeOut | None = None
    reviewed: bool = False
    # o que o front pode oferecer agora
    can_pay: bool
    can_cancel: bool
    can_mark_transferred: bool
    can_confirm: bool
    can_dispute: bool
    can_reply_dispute: bool
    can_review: bool
    created_at: datetime | None = None  # quando a reserva foi feita (primeira etapa da linha do tempo)
    transfer_to: str | None = None  # conta do comprador na ticketeira: o comprador vê sempre; o vendedor só depois do pagamento
    seller_phone: str | None = None  # telefone do vendedor (só dígitos, com DDD, sem +55): só o comprador, e só depois do pagamento
    payment: dict | None = None  # provedor falso: {"provider": "fake"}; o gateway real traz os dados da cobrança


# ---------------------------------------------------------------- admin


class SettingsIn(Camel):
    fee_bps: int = Field(ge=0, le=3000)


class SettingsOut(Camel):
    fee_bps: int


class AdminEventIn(Camel):
    ticketing_sold_out: bool
    resale_open: bool


class AdminEventOut(Camel):
    id: str
    date: date
    city: str
    venue: str
    time: str
    time_readable: bool  # sem horário legível a revenda não abre
    ticketing_sold_out: bool
    resale_open: bool
    is_open: bool  # as duas chaves ligadas, show futuro e horário legível
    pending_listings: int
    live_listings: int


class RejectIn(Camel):
    reason: str = Field(min_length=1, max_length=300)


class DecideIn(Camel):
    decision: Literal["refund", "release"]
    note: str = Field(default="", max_length=500)


class AdminListingOut(Camel):
    id: str
    status: str
    event_id: str
    event_city: str
    ticket_label: str
    face_cents: int
    qty_total: int
    qty_available: int
    unit_price_cents: int
    review_reason: str
    attempts: int
    seller: SellerOut
    codes: list[str]  # os códigos dos ingressos (decifrados só para o admin)
    proof_mime: str
    proof_url: str  # download autenticado
    verifier_status: str
    verifier_detail: str
    history: list[dict]
    created_at: str


class LedgerOut(Camel):
    id: str
    order_id: str
    kind: str
    debit_account: str
    credit_account: str
    amount_cents: int
    status: str
    provider_ref: str
    created_at: datetime


class AdminDisputeOut(Camel):
    id: str
    order_id: str
    status: str
    reason_code: str
    description: str
    seller_reply: str
    resolution: str
    decision_note: str
    created_at: str
    order: OrderOut
