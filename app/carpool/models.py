"""Tabelas das caronas por show. Valores em centavos inteiros, datas em UTC.
Nenhuma tabela aqui apaga em cascata: há dinheiro retido e trilha de auditoria."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import new_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Viagem
R_OPEN, R_CANCELLED = "open", "cancelled"
# Reserva de vagas: reserved (vagas seguradas por 15 min) -> paid (valor retido) -> completed (liberado ao motorista)
#                   ou cancelled (nunca pagou) / refunded (pagou e foi devolvido)
B_RESERVED, B_PAID, B_COMPLETED, B_CANCELLED, B_REFUNDED = "reserved", "paid", "completed", "cancelled", "refunded"


class Ride(Base):
    """Uma viagem oferecida por um fã para um show: quantas vagas e quanto cada uma custa."""

    __tablename__ = "carpool_rides"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    origin_city: Mapped[str] = mapped_column(String(80))
    meeting_point: Mapped[str] = mapped_column(String(160), default="")
    depart_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seats_total: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)  # por vaga
    car: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(12), default=R_OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RideBooking(Base):
    """Vagas que um fã reservou numa viagem."""

    __tablename__ = "carpool_bookings"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    ride_id: Mapped[str] = mapped_column(ForeignKey("carpool_rides.id", ondelete="RESTRICT"), index=True)
    passenger_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    seats: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)  # vagas x preço, no momento da reserva
    status: Mapped[str] = mapped_column(String(12), default=B_RESERVED)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # fim do prazo da reserva sem pagar
    payment_method: Mapped[str] = mapped_column(String(12), default="")  # pix | cartao
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RideLedger(Base):
    """Trilha do dinheiro: hold (pagou e ficou retido), release (liberado ao motorista) e refund (devolvido)."""

    __tablename__ = "carpool_ledger"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=new_id)
    booking_id: Mapped[str] = mapped_column(ForeignKey("carpool_bookings.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # hold | release | refund
    amount_cents: Mapped[int] = mapped_column(Integer)
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)  # só no release: parte que fica com a plataforma
    note: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
