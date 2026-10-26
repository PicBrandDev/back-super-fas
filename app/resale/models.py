"""Tabelas da revenda de ingressos. Valores em centavos inteiros, datas em UTC.
Nenhuma tabela aqui apaga em cascata: há dinheiro retido e trilha de auditoria (apagar show, tipo de ingresso ou usuário
com revenda em andamento é bloqueado)."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import new_id
from .base import L_PENDING, O_RESERVED, utcnow


class UserIdentity(Base):
    """CPF e telefone do vendedor, FORA da tabela users (nenhum serializer de usuário os devolve)."""

    __tablename__ = "resale_identities"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    cpf_enc: Mapped[str] = mapped_column(String(255))
    phone_enc: Mapped[str] = mapped_column(String(255))
    cpf_hash: Mapped[str] = mapped_column(String(64), unique=True)  # detecta o mesmo CPF em duas contas
    cpf_last2: Mapped[str] = mapped_column(String(2))
    phone_last4: Mapped[str] = mapped_column(String(4))
    level: Mapped[str] = mapped_column(String(10), default="declared")  # declared | verified (MFA por e-mail: ponto de extensão)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResaleSetting(Base):
    """Taxa da intermediação por ambiente."""

    __tablename__ = "resale_settings"

    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"), primary_key=True)
    fee_bps: Mapped[int] = mapped_column(Integer, default=0)  # 100 bps = 1%
    updated_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    __table_args__ = (CheckConstraint("fee_bps >= 0 AND fee_bps <= 3000", name="ck_resale_fee_bps"),)


class ResaleEvent(Base):
    """Chaves por show: a revenda só existe com as duas ligadas (e show futuro). Quem liga é o admin do ambiente."""

    __tablename__ = "resale_events"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), primary_key=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"), index=True)
    ticketing_sold_out: Mapped[bool] = mapped_column(Boolean, default=False)  # esgotou na ticketeira oficial
    resale_open: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Listing(Base):
    """Anúncio de um lote: N ingressos de um tipo, a um preço por ingresso (teto = valor de face)."""

    __tablename__ = "resale_listings"
    __table_args__ = (
        CheckConstraint("qty_available >= 0 AND qty_available <= qty_total", name="ck_resale_listing_qty"),
        CheckConstraint("unit_price_cents > 0 AND unit_price_cents <= face_cents", name="ck_resale_listing_price"),
        Index("ix_resale_listing_event_status", "event_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    event_ticket_id: Mapped[str | None] = mapped_column(ForeignKey("event_tickets.id", ondelete="SET NULL"), nullable=True)
    seller_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    ticket_label: Mapped[str] = mapped_column(String(120))  # cópia do tipo (Pista, Camarote...) no momento do anúncio
    face_cents: Mapped[int] = mapped_column(Integer)  # cópia do valor de face (o teto)
    qty_total: Mapped[int] = mapped_column(Integer)
    qty_available: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=L_PENDING)
    review_reason: Mapped[str] = mapped_column(String(300), default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)  # envios da prova
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Proof(Base):
    """Prova do ingresso (imagem/PDF em pasta privada) e os códigos informados (cifrados)."""

    __tablename__ = "resale_proofs"

    listing_id: Mapped[str] = mapped_column(ForeignKey("resale_listings.id", ondelete="RESTRICT"), primary_key=True)
    file_path: Mapped[str] = mapped_column(String(255))  # nome do arquivo dentro da pasta privada
    mime: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    codes_enc: Mapped[str] = mapped_column(Text)  # lista JSON cifrada dos N códigos
    verifier_status: Mapped[str] = mapped_column(String(16), default="unknown")  # unknown | valid | invalid | already_listed
    verifier_detail: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TicketCode(Base):
    """Um código de ingresso anunciado. Só um anúncio ativo por código em cada show (impede vender duas vezes)."""

    __tablename__ = "resale_ticket_codes"
    __table_args__ = (
        Index("ux_resale_code_active", "event_id", "code_hash", unique=True, sqlite_where=text("active = 1"), postgresql_where=text("active")),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    listing_id: Mapped[str] = mapped_column(ForeignKey("resale_listings.id", ondelete="RESTRICT"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    """Compra (reserva) de parte ou do todo de um lote, com o valor retido até a confirmação."""

    __tablename__ = "resale_orders"
    __table_args__ = (
        UniqueConstraint("buyer_id", "idempotency_key"),
        CheckConstraint("qty > 0", name="ck_resale_order_qty"),
        CheckConstraint("gross_cents = qty * unit_price_cents", name="ck_resale_order_gross"),
        CheckConstraint("fee_cents + seller_net_cents = gross_cents", name="ck_resale_order_split"),
        Index("ix_resale_order_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    listing_id: Mapped[str] = mapped_column(ForeignKey("resale_listings.id", ondelete="RESTRICT"), index=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    buyer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    seller_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    gross_cents: Mapped[int] = mapped_column(Integer)  # o que o comprador paga
    fee_bps: Mapped[int] = mapped_column(Integer, default=0)  # taxa congelada na criação do pedido
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    seller_net_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(18), default=O_RESERVED)
    reserved_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transfer_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirm_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str] = mapped_column(String(40), default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payment_ref: Mapped[str] = mapped_column(String(80), default="")
    # e-mail da conta do comprador na ticketeira (cifrado): para onde o vendedor transfere; ele só vê depois do pagamento
    transfer_to_enc: Mapped[str] = mapped_column(String(600), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerEntry(Base):
    """Livro-razão só de inclusão (partida dobrada). UNIQUE (pedido, tipo) é a trava de idempotência contábil."""

    __tablename__ = "resale_ledger"
    __table_args__ = (UniqueConstraint("order_id", "kind"), CheckConstraint("amount_cents > 0", name="ck_resale_ledger_amount"))

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("resale_orders.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # hold | release_seller | fee | refund
    debit_account: Mapped[str] = mapped_column(String(20))  # buyer_external | escrow | seller_payable | platform_fee
    credit_account: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | processing | settled | failed
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # quando um processo assumiu o lançamento
    provider_ref: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dispute(Base):
    __tablename__ = "resale_disputes"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("resale_orders.id", ondelete="RESTRICT"), unique=True)
    opened_by: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(30))  # not_received | invalid_ticket | wrong_type | other
    description: Mapped[str] = mapped_column(String(1000), default="")
    seller_reply: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | resolved
    resolution: Mapped[str] = mapped_column(String(10), default="")  # refund | release
    decided_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(500), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    """Avaliação do comprador depois da venda concluída (1 por pedido)."""

    __tablename__ = "resale_reviews"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_resale_review_rating"),)

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("resale_orders.id", ondelete="RESTRICT"), unique=True)
    buyer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    seller_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(500), default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Audit(Base):
    """Trilha de auditoria de toda transição (actor_id nulo = sistema)."""

    __tablename__ = "resale_audit"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    entity: Mapped[str] = mapped_column(String(16), index=True)  # listing | order | dispute | event | setting
    entity_id: Mapped[str] = mapped_column(String(20), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20), default="")
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
