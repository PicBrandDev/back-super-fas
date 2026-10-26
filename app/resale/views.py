"""Monta as respostas (OrderOut, ListingOut...) a partir dos modelos. Fica separado das regras para as rotas ficarem finas."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import br_date
from . import access, payments, trust
from .base import L_LIVE, L_PENDING, L_REJECTED, MAX_ATTEMPTS, O_ACTIVE, O_AWAITING, O_COMPLETED, O_DISPUTED, O_RESERVED, O_TRANSFERRED, aware, decrypt, utcnow
from .models import Dispute, Listing, Order, Review, UserIdentity
from .schemas import DisputeOut, ListingOut, MyListingOut, OrderOut, SellerOut


def dispute_out(d: Dispute) -> DisputeOut:
    return DisputeOut(
        id=d.id, order_id=d.order_id, status=d.status, reason_code=d.reason_code, description=d.description, seller_reply=d.seller_reply,
        resolution=d.resolution, decision_note=d.decision_note, created_at=br_date(d.created_at.date()),
    )


def listing_out(li: Listing, seller: SellerOut) -> ListingOut:
    return ListingOut(
        id=li.id, event_id=li.event_id, ticket_id=li.event_ticket_id, ticket_label=li.ticket_label, face_cents=li.face_cents, qty_total=li.qty_total,
        qty_available=li.qty_available, unit_price_cents=li.unit_price_cents, created_at=br_date(li.created_at.date()), seller=seller,
    )


def my_listing_out(db: Session, li: Listing) -> MyListingOut:
    e = db.get(m.Event, li.event_id)
    active = db.scalar(select(func.count(Order.id)).where(Order.listing_id == li.id, Order.status.in_(O_ACTIVE))) or 0
    return MyListingOut(
        id=li.id, event_id=li.event_id, event_city=e.city, event_date=e.date, ticket_label=li.ticket_label, face_cents=li.face_cents, qty_total=li.qty_total,
        qty_available=li.qty_available, unit_price_cents=li.unit_price_cents, status=li.status, review_reason=li.review_reason, attempts=li.attempts,
        can_resubmit=li.status == L_REJECTED and li.attempts < MAX_ATTEMPTS, can_cancel=li.status in (L_PENDING, L_REJECTED, L_LIVE) and not active,
        active_orders=active, created_at=br_date(li.created_at.date()),
    )


def order_out(db: Session, artist: m.Artist, o: Order, viewer: m.User | None, sellers: dict[str, SellerOut] | None = None) -> OrderOut:
    """`viewer` None = visão do admin (vê as duas pontas). Comprador vê o vendedor completo; vendedor vê só o handle do comprador."""
    li = db.get(Listing, o.listing_id)
    e = db.get(m.Event, o.event_id)
    role = "seller" if viewer and viewer.id == o.seller_id else "buyer"
    buyer = db.get(m.User, o.buyer_id)
    seller_sum = (sellers or trust.sellers(db, artist, [o.seller_id])).get(o.seller_id)
    d = db.scalar(select(Dispute).where(Dispute.order_id == o.id))
    now = utcnow()
    is_buyer, is_seller = role == "buyer" and viewer is not None, role == "seller"
    start_ok = o.status == O_RESERVED and aware(o.reserved_until) >= now
    reviewed = bool(db.scalar(select(Review.id).where(Review.order_id == o.id)))
    # o vendedor só recebe a conta de destino quando o pagamento entrou (antes disso não há o que transferir)
    paid = o.status in (O_AWAITING, O_TRANSFERRED, O_DISPUTED, O_COMPLETED)
    show_dest = bool(o.transfer_to_enc) and (role == "buyer" or viewer is None or paid)
    # e o comprador só recebe o WhatsApp do vendedor depois de pagar (para combinar a transferência)
    seller_ident = db.get(UserIdentity, o.seller_id) if paid and is_buyer else None
    return OrderOut(
        id=o.id, status=o.status, role=role, listing_id=o.listing_id, event_id=o.event_id, event_city=e.city, event_date=e.date, event_venue=e.venue,
        ticket_label=li.ticket_label if li else "", qty=o.qty, unit_price_cents=o.unit_price_cents, gross_cents=o.gross_cents, fee_cents=o.fee_cents,
        seller_net_cents=o.seller_net_cents, reserved_until=aware(o.reserved_until), paid_at=aware(o.paid_at), transfer_deadline=aware(o.transfer_deadline),
        transferred_at=aware(o.transferred_at), confirm_deadline=aware(o.confirm_deadline), closed_at=aware(o.closed_at), close_reason=o.close_reason,
        counterparty=seller_sum if role == "buyer" else None,
        buyer_handle=trust.public_handle(buyer) if role == "seller" or viewer is None else None,
        buyer_name=trust.short_name(buyer) if role == "seller" or viewer is None else None,
        dispute=dispute_out(d) if d else None, reviewed=reviewed,
        can_pay=bool(is_buyer and start_ok and payments.is_fake()), can_cancel=bool(is_buyer and start_ok),
        can_mark_transferred=bool(is_seller and o.status == O_AWAITING), can_confirm=bool(is_buyer and o.status == O_TRANSFERRED),
        can_dispute=bool(is_buyer and o.status == O_TRANSFERRED and o.confirm_deadline and aware(o.confirm_deadline) >= now),
        can_reply_dispute=bool(is_seller and o.status == O_DISPUTED and d and d.status == "open"),
        can_review=bool(is_buyer and o.status == O_COMPLETED and not reviewed),
        payment={"provider": "fake"} if payments.is_fake() else None,
        created_at=aware(o.created_at), transfer_to=decrypt(o.transfer_to_enc) if show_dest else None,
        seller_phone=decrypt(seller_ident.phone_enc) if seller_ident else None,
    )


def orders_out(db: Session, artist: m.Artist, orders: list[Order], viewer: m.User | None) -> list[OrderOut]:
    sellers = trust.sellers(db, artist, [o.seller_id for o in orders])
    return [order_out(db, artist, o, viewer, sellers) for o in orders]
