"""Proteções contra apagar ou mudar o que sustenta a revenda (há dinheiro retido e trilha de auditoria)."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models as m
from .base import O_ACTIVE, ResaleError
from .models import Listing, Order, ResaleEvent, ResaleSetting


def ensure_deletable(db: Session, obj) -> None:
    """Show com revenda registrada, tipo de ingresso com pedido em andamento não podem ser apagados."""
    if isinstance(obj, m.Event):
        if db.scalar(select(Listing.id).where(Listing.event_id == obj.id).limit(1)) or db.get(ResaleEvent, obj.id):
            raise ResaleError("HAS_RESALE", "Este show tem revenda de ingressos registrada e não pode ser apagado. Desligue a revenda dele no lugar.", 409)
    elif isinstance(obj, m.EventTicket):
        q = select(Order.id).join(Listing, Listing.id == Order.listing_id).where(Listing.event_ticket_id == obj.id, Order.status.in_(O_ACTIVE)).limit(1)
        if db.scalar(q):
            raise ResaleError("HAS_ACTIVE_ORDERS", "Há compras da revenda em andamento com este tipo de ingresso. Conclua-as antes de apagar.", 409)


def ensure_editable(db: Session, obj, data: dict) -> None:
    """Mudar a data ou o horário do show com compras em andamento deixaria os prazos de transferência errados."""
    if isinstance(obj, m.Event) and ("date" in data or "time" in data):
        if db.scalar(select(Order.id).where(Order.event_id == obj.id, Order.status.in_(O_ACTIVE)).limit(1)):
            raise ResaleError("CHANGE_BLOCKED", "Há compras da revenda em andamento neste show: não dá para mudar a data ou o horário agora.", 409)


def release_artist(db: Session, artist: m.Artist) -> None:
    """Antes de apagar um ambiente: bloqueia se houve revenda; senão remove as chaves e a taxa (que travam a exclusão)."""
    if db.scalar(select(Listing.id).where(Listing.artist_id == artist.id).limit(1)):
        raise ResaleError("HAS_RESALE", "Este ambiente tem revenda de ingressos registrada e não pode ser apagado.", 409)
    db.execute(delete(ResaleEvent).where(ResaleEvent.artist_id == artist.id))
    db.execute(delete(ResaleSetting).where(ResaleSetting.artist_id == artist.id))
