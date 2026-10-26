"""Pedidos da revenda: reserva atômica do saldo, pagamento retido (escrow), transferência, confirmação, disputa e a
varredura de prazos. Toda mudança de estado é um UPDATE condicional (`access.cas`): só quem vence a troca executa os efeitos
(devolver saldo, lançar no livro-razão), então ações repetidas ou concorrentes nunca agem duas vezes."""

import re
from datetime import datetime, timedelta

from sqlalchemy import false, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from . import access, identity, payments
from .base import (
    BLOCK_BUY_BEFORE_SHOW_H,
    BR_TZ,
    CONFIRM_HOURS,
    L_LIVE,
    L_PENDING,
    MAX_ACTIVE_RESERVATIONS,
    O_ACTIVE,
    O_AWAITING,
    O_CANCELLED,
    O_COMPLETED,
    O_DISPUTED,
    O_EXPIRED,
    O_REFUNDED,
    O_RESERVED,
    O_TRANSFERRED,
    RESERVE_MINUTES,
    TRANSFER_HOURS,
    TRANSFER_MIN_BEFORE_SHOW_H,
    ResaleError,
    aware,
    conflict,
    encrypt,
    forbidden,
    not_found,
    split_fee,
    utcnow,
)
from .models import Dispute, LedgerEntry, Listing, Order, ResaleSetting, Review

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DISPUTE_REASONS = ("not_received", "invalid_ticket", "wrong_type", "other")


# ---------------------------------------------------------------- leitura e permissão


def get_order(db: Session, artist: m.Artist, order_id: str) -> Order:
    o = db.get(Order, order_id)
    if not o or o.artist_id != artist.id:
        raise not_found("Pedido não encontrado.")
    return o


def _party(o: Order, user: m.User, role: str) -> None:
    ok = o.buyer_id == user.id if role == "buyer" else o.seller_id == user.id
    if not ok:
        raise forbidden("NOT_PARTY", "Você não participa deste pedido." if role == "buyer" else "Este pedido não é de uma venda sua.")


def fee_bps(db: Session, artist_id: str) -> int:
    s = db.get(ResaleSetting, artist_id)
    return s.fee_bps if s else 0


# ---------------------------------------------------------------- efeitos das transições


def _restore_qty(db: Session, o: Order) -> None:
    """Devolve ao anúncio as unidades de uma reserva que não virou venda (expirada ou cancelada)."""
    db.execute(
        update(Listing).where(Listing.id == o.listing_id, Listing.qty_available + o.qty <= Listing.qty_total).values(qty_available=Listing.qty_available + o.qty)
    )


def _transfer_deadline(db: Session, o: Order, paid_at: datetime) -> datetime:
    """Até 24h depois do pagamento ou até 2h antes do show, o que vier antes."""
    deadline = paid_at + timedelta(hours=TRANSFER_HOURS)
    start = access.event_start(db.get(m.Event, o.event_id))
    return min(deadline, start - timedelta(hours=TRANSFER_MIN_BEFORE_SHOW_H)) if start else deadline


def _mark_paid(db: Session, o: Order, ref: str, actor: m.User | None) -> bool:
    """reserved -> awaiting_transfer com o valor retido. Devolve False se outra requisição já mudou o pedido."""
    now = utcnow()
    if not access.cas(db, Order, o.id, O_RESERVED, status=O_AWAITING, paid_at=now, transfer_deadline=_transfer_deadline(db, o, now), payment_ref=ref):
        return False
    payments.post_hold(db, o)
    access.audit(db, "order", o.id, "paid", actor, O_RESERVED, O_AWAITING)
    return True


def _complete(db: Session, o: Order, actor: m.User | None, frm: tuple[str, ...], reason: str) -> bool:
    now = utcnow()
    if not access.cas(db, Order, o.id, frm, status=O_COMPLETED, confirmed_at=now, closed_at=now, close_reason=reason):
        return False
    payments.post_release(db, o)
    access.audit(db, "order", o.id, "completed", actor, "|".join(frm), O_COMPLETED, reason=reason)
    return True


def _refund(db: Session, o: Order, actor: m.User | None, frm: tuple[str, ...], reason: str) -> bool:
    """Devolve o valor ao comprador. O saldo do anúncio NÃO volta: o ingresso não foi entregue e o vendedor falhou."""
    if not access.cas(db, Order, o.id, frm, status=O_REFUNDED, closed_at=utcnow(), close_reason=reason):
        return False
    payments.post_refund(db, o)
    access.audit(db, "order", o.id, "refunded", actor, "|".join(frm), O_REFUNDED, reason=reason)
    return True


# ---------------------------------------------------------------- varredura de prazos (preguiçosa e idempotente)


def sweep(db: Session, *, order_id: str | None = None, listing_id: str | None = None, event_id: str | None = None, user_id: str | None = None, artist_id: str | None = None, seller_id: str | None = None, now: datetime | None = None) -> None:
    """Aplica os prazos vencidos. Sem filtro varre tudo (o cron futuro); com filtro, só o escopo lido/alterado agora."""
    now = now or utcnow()

    def scoped(q):
        if order_id:
            q = q.where(Order.id == order_id)
        if listing_id:
            q = q.where(Order.listing_id == listing_id)
        if event_id:
            q = q.where(Order.event_id == event_id)
        if artist_id:
            q = q.where(Order.artist_id == artist_id)
        if user_id:
            q = q.where((Order.buyer_id == user_id) | (Order.seller_id == user_id))
        return q

    touched: list[Order] = []
    # 1. reservas que o comprador não pagou em 15 min: o saldo volta ao anúncio
    for o in db.scalars(scoped(select(Order).where(Order.status == O_RESERVED, Order.reserved_until < now))).all():
        if access.cas(db, Order, o.id, O_RESERVED, status=O_EXPIRED, closed_at=now, close_reason="reservation_expired"):
            _restore_qty(db, o)
            access.audit(db, "order", o.id, "expired", None, O_RESERVED, O_EXPIRED)
    # 2. vendedor não transferiu no prazo: reembolso automático
    for o in db.scalars(scoped(select(Order).where(Order.status == O_AWAITING, Order.transfer_deadline < now))).all():
        if _refund(db, o, None, (O_AWAITING,), "seller_no_transfer"):
            touched.append(o)
    # 3. comprador não confirmou nem abriu disputa: libera ao vendedor (disputa aberta congela a liberação)
    for o in db.scalars(scoped(select(Order).where(Order.status == O_TRANSFERRED, Order.confirm_deadline < now))).all():
        if _complete(db, o, None, (O_TRANSFERRED,), "auto_release"):
            touched.append(o)
    # 4. anúncios de shows que já começaram
    q = select(Listing).where(Listing.status.in_((L_LIVE, L_PENDING)))
    if listing_id:
        q = q.where(Listing.id == listing_id)
    elif event_id:
        q = q.where(Listing.event_id == event_id)
    elif artist_id:
        q = q.where(Listing.artist_id == artist_id)
    elif seller_id:
        q = q.where(Listing.seller_id == seller_id)
    elif order_id or user_id:
        q = q.where(false())  # escopo de pedido/usuário não fecha anúncios
    for li in db.scalars(q).all():
        e = db.get(m.Event, li.event_id)
        start = access.event_start(e)
        if (start and start < now) or (not start and e.date < now.astimezone(BR_TZ).date()):
            if access.cas(db, Listing, li.id, (L_LIVE, L_PENDING), status="closed"):
                access.audit(db, "listing", li.id, "closed", None, li.status, "closed", reason="show_started")
    db.commit()
    # 5. lançamentos pendentes (padrão outbox): fala com o provedor depois do commit
    pending = select(Order).join(LedgerEntry, LedgerEntry.order_id == Order.id).where(LedgerEntry.status == "pending").distinct()
    for o in db.scalars(scoped(pending)).all():
        payments.settle(db, o)


# ---------------------------------------------------------------- reserva


def _transfer_email(raw: str, buyer: m.User) -> str:
    v = (raw or "").strip() or (buyer.email or "").strip()
    if not EMAIL_RE.match(v):
        raise ResaleError("TRANSFER_TO_INVALID", "Informe o e-mail da sua conta na ticketeira.")
    return v.lower()


def reserve(db: Session, artist: m.Artist, buyer: m.User, listing_id: str, qty: int, idem_key: str | None, transfer_to: str = "") -> Order:
    if idem_key:
        prior = db.scalar(select(Order).where(Order.buyer_id == buyer.id, Order.idempotency_key == idem_key))
        if prior:  # repetição do mesmo pedido: devolve o que já existe
            if prior.listing_id != listing_id or prior.qty != qty:
                raise conflict("IDEMPOTENCY_CONFLICT", "Esta chave de idempotência já foi usada em outro pedido.")
            return prior
    li = db.get(Listing, listing_id)
    if not li or li.artist_id != artist.id:
        raise not_found("Anúncio não encontrado.")
    transfer_email = _transfer_email(transfer_to, buyer)
    sweep(db, listing_id=li.id, user_id=None)
    sweep(db, user_id=buyer.id)
    db.refresh(li)
    can_buy, _, missing = identity.eligibility(db, artist, buyer)
    if not can_buy:
        raise forbidden("NOT_ELIGIBLE", "Complete o cadastro para comprar: " + ", ".join(missing) + ".")
    e = db.get(m.Event, li.event_id)
    access.ensure_open(db, e, BLOCK_BUY_BEFORE_SHOW_H)
    if li.status != L_LIVE:
        raise conflict("LISTING_NOT_LIVE", "Este anúncio não está disponível.")
    if li.seller_id == buyer.id:
        raise forbidden("OWN_LISTING", "Você não pode comprar o seu próprio anúncio.")
    mine, theirs = identity.get(db, buyer), identity.get(db, db.get(m.User, li.seller_id))
    if mine and theirs and mine.cpf_hash == theirs.cpf_hash:
        raise forbidden("OWN_LISTING", "Você não pode comprar o seu próprio anúncio.")
    if not 1 <= qty <= li.qty_total:
        raise ResaleError("QTY_INVALID", "Quantidade inválida para este anúncio.")
    active = db.scalar(select(func.count(Order.id)).where(Order.buyer_id == buyer.id, Order.status == O_RESERVED)) or 0
    if active >= MAX_ACTIVE_RESERVATIONS:
        raise ResaleError("TOO_MANY_RESERVATIONS", "Você já tem 3 reservas aguardando pagamento. Pague ou cancele uma delas.", 429)
    if db.scalar(select(Order.id).where(Order.buyer_id == buyer.id, Order.listing_id == li.id, Order.status == O_RESERVED)):
        raise conflict("ALREADY_RESERVED", "Você já tem uma reserva neste anúncio. Pague ou cancele antes de reservar de novo.")
    # o teto de preço vale de novo agora: se o valor de face baixou depois do anúncio, ele volta para análise
    t = db.get(m.EventTicket, li.event_ticket_id) if li.event_ticket_id else None
    if t and t.price_cents and li.unit_price_cents > t.price_cents:
        if access.cas(db, Listing, li.id, L_LIVE, status=L_PENDING, review_reason="O valor de face mudou: revise o preço."):
            db.commit()
        raise conflict("PRICE_ABOVE_FACE", "O preço deste anúncio ficou acima do valor de face e foi pausado.")

    # reserva atômica do saldo: só uma de duas compras simultâneas passa (SQLite serializa o escritor; no Postgres o
    # lock da linha reavalia o WHERE). O CHECK qty_available >= 0 é a rede de segurança.
    res = db.execute(
        update(Listing).where(Listing.id == li.id, Listing.status == L_LIVE, Listing.qty_available >= qty).values(qty_available=Listing.qty_available - qty).execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.rollback()
        raise conflict("QTY_UNAVAILABLE", "Não há mais essa quantidade disponível neste anúncio.")
    bps = fee_bps(db, artist.id)
    gross = qty * li.unit_price_cents
    fee, net = split_fee(gross, bps)
    o = Order(
        listing_id=li.id, artist_id=artist.id, event_id=li.event_id, buyer_id=buyer.id, seller_id=li.seller_id, qty=qty,
        unit_price_cents=li.unit_price_cents, gross_cents=gross, fee_bps=bps, fee_cents=fee, seller_net_cents=net,
        status=O_RESERVED, reserved_until=utcnow() + timedelta(minutes=RESERVE_MINUTES), idempotency_key=idem_key,
        transfer_to_enc=encrypt(transfer_email),
    )
    db.add(o)
    try:
        db.flush()
    except IntegrityError:  # a mesma chave chegou duas vezes ao mesmo tempo
        db.rollback()
        prior = db.scalar(select(Order).where(Order.buyer_id == buyer.id, Order.idempotency_key == idem_key)) if idem_key else None
        if prior:
            return prior
        raise
    access.audit(db, "order", o.id, "reserved", buyer, to=O_RESERVED, qty=qty, gross_cents=gross)
    db.commit()
    db.refresh(o)
    return o


# ---------------------------------------------------------------- ações do pedido


def _same(o: Order, target: str) -> bool:
    return o.status == target


def pay_fake(db: Session, buyer: m.User, o: Order) -> Order:
    """Pagamento simulado (só com o provedor falso): retém o valor e abre o prazo de transferência."""
    if not payments.is_fake():
        raise ResaleError("NOT_AVAILABLE", "O pagamento simulado está desligado.", 404)
    _party(o, buyer, "buyer")
    sweep(db, order_id=o.id)
    db.refresh(o)
    if o.status in (O_AWAITING, O_TRANSFERRED, O_COMPLETED, O_DISPUTED):
        return o  # idempotente: já pago
    if o.status != O_RESERVED:
        raise conflict("RESERVATION_EXPIRED" if o.status == O_EXPIRED else "INVALID_STATE", "A reserva expirou. Reserve de novo." if o.status == O_EXPIRED else "Este pedido não pode mais ser pago.")
    if not _mark_paid(db, o, "", buyer):  # a referência do provedor entra no livro-razão quando o lançamento é liquidado
        db.rollback()
        db.refresh(o)
        return o
    db.commit()
    payments.settle(db, o)
    db.refresh(o)
    return o


def confirm_payment(db: Session, o: Order, ref: str, amount_cents: int | None = None) -> Order:
    """Pagamento confirmado por um gateway real (webhook assinado). O valor pago tem que ser igual ao bruto do pedido.
    Pagamento tardio (reserva expirada OU cancelada pelo comprador) é reembolsado: o dinheiro entra no escrow e volta."""
    if amount_cents is not None and amount_cents != o.gross_cents:
        access.audit(db, "order", o.id, "payment_amount_mismatch", None, o.status, o.status, paid=amount_cents, expected=o.gross_cents)
        db.commit()
        raise ResaleError("AMOUNT_MISMATCH", "O valor pago não confere com o pedido.", 400)
    sweep(db, order_id=o.id)
    db.refresh(o)
    if o.status == O_RESERVED:
        if _mark_paid(db, o, ref, None):
            db.commit()
    elif o.status in (O_EXPIRED, O_CANCELLED):
        payments.post_hold(db, o)
        if _refund(db, o, None, (O_EXPIRED, O_CANCELLED), "late_payment"):
            db.commit()
    payments.settle(db, o)
    db.refresh(o)
    return o


def cancel(db: Session, buyer: m.User, o: Order) -> Order:
    _party(o, buyer, "buyer")
    sweep(db, order_id=o.id)
    db.refresh(o)
    if _same(o, O_CANCELLED):
        return o
    if o.status != O_RESERVED:
        raise conflict("INVALID_STATE", "Só dá para cancelar uma reserva que ainda não foi paga.")
    if access.cas(db, Order, o.id, O_RESERVED, status=O_CANCELLED, closed_at=utcnow(), close_reason="buyer_cancelled"):
        _restore_qty(db, o)
        access.audit(db, "order", o.id, "cancelled", buyer, O_RESERVED, O_CANCELLED)
        db.commit()
    db.refresh(o)
    return o


def mark_transferred(db: Session, seller: m.User, o: Order) -> Order:
    _party(o, seller, "seller")
    sweep(db, order_id=o.id)
    db.refresh(o)
    if o.status in (O_TRANSFERRED, O_COMPLETED, O_DISPUTED):
        return o
    if o.status != O_AWAITING:
        raise conflict("INVALID_STATE", "Este pedido não está aguardando a transferência.")
    now = utcnow()
    if access.cas(db, Order, o.id, O_AWAITING, status=O_TRANSFERRED, transferred_at=now, confirm_deadline=now + timedelta(hours=CONFIRM_HOURS)):
        access.audit(db, "order", o.id, "transferred", seller, O_AWAITING, O_TRANSFERRED)
        db.commit()
    db.refresh(o)
    return o


def confirm(db: Session, buyer: m.User, o: Order) -> Order:
    _party(o, buyer, "buyer")
    sweep(db, order_id=o.id)
    db.refresh(o)
    if o.status == O_COMPLETED:
        return o
    if o.status == O_DISPUTED:
        raise conflict("DISPUTED", "Há uma disputa aberta neste pedido. O admin vai decidir.")
    if o.status != O_TRANSFERRED:
        raise conflict("INVALID_STATE", "O vendedor ainda não marcou o ingresso como transferido.")
    if _complete(db, o, buyer, (O_TRANSFERRED,), "buyer_confirmed"):
        db.commit()
        payments.settle(db, o)
    db.refresh(o)
    return o


def dispute(db: Session, buyer: m.User, o: Order, reason_code: str, description: str) -> Order:
    _party(o, buyer, "buyer")
    if reason_code not in DISPUTE_REASONS:
        raise ResaleError("REASON_INVALID", "Motivo da disputa inválido.")
    sweep(db, order_id=o.id)
    db.refresh(o)
    if o.status == O_DISPUTED:
        return o
    if o.status != O_TRANSFERRED:
        raise conflict("INVALID_STATE", "Só dá para abrir disputa depois que o vendedor marcou a transferência e antes do prazo de confirmação.")
    if not access.cas(db, Order, o.id, O_TRANSFERRED, status=O_DISPUTED):
        db.rollback()
        db.refresh(o)
        return o
    db.add(Dispute(order_id=o.id, opened_by=buyer.id, reason_code=reason_code, description=(description or "").strip()[:1000]))
    access.audit(db, "order", o.id, "disputed", buyer, O_TRANSFERRED, O_DISPUTED, reason=reason_code)
    db.commit()
    db.refresh(o)
    return o


def dispute_reply(db: Session, seller: m.User, o: Order, text: str) -> Dispute:
    _party(o, seller, "seller")
    d = db.scalar(select(Dispute).where(Dispute.order_id == o.id))
    if not d or d.status != "open":
        raise conflict("NO_OPEN_DISPUTE", "Não há disputa aberta neste pedido.")
    d.seller_reply = (text or "").strip()[:1000]
    access.audit(db, "dispute", d.id, "seller_replied", seller)
    db.commit()
    return d


def decide(db: Session, admin: m.User, o: Order, decision: str, note: str) -> Order:
    """O admin do ambiente decide a disputa: reembolsa o comprador ou libera ao vendedor. Quem é parte do pedido não decide."""
    if decision not in ("refund", "release"):
        raise ResaleError("DECISION_INVALID", "Decida entre reembolsar o comprador ou liberar ao vendedor.")
    if admin.id in (o.buyer_id, o.seller_id):
        raise forbidden("CONFLICT_OF_INTEREST", "Você é parte deste pedido: outro admin precisa decidir.")
    d = db.scalar(select(Dispute).where(Dispute.order_id == o.id))
    if not d or d.status != "open":
        raise conflict("NO_OPEN_DISPUTE", "Esta disputa já foi decidida ou não existe.")
    done = _complete(db, o, admin, (O_DISPUTED,), "dispute_release") if decision == "release" else _refund(db, o, admin, (O_DISPUTED,), "dispute_refund")
    if not done:
        db.rollback()
        raise conflict("NO_OPEN_DISPUTE", "Esta disputa já foi decidida.")
    d.status, d.resolution, d.decided_by, d.decision_note, d.decided_at = "resolved", decision, admin.id, (note or "").strip()[:500], utcnow()
    access.audit(db, "dispute", d.id, "decided", admin, "open", "resolved", decision=decision)
    db.commit()
    payments.settle(db, o)
    db.refresh(o)
    return o


def admin_refund(db: Session, admin: m.User, o: Order, note: str) -> Order:
    """Admin reembolsa um pedido pago que ainda não foi transferido (ex.: vendedor sumiu)."""
    if admin.id in (o.buyer_id, o.seller_id):
        raise forbidden("CONFLICT_OF_INTEREST", "Você é parte deste pedido: outro admin precisa decidir.")
    if o.status == O_REFUNDED:
        return o
    if o.status != O_AWAITING:
        raise conflict("INVALID_STATE", "Só dá para reembolsar um pedido pago que ainda não foi transferido.")
    if _refund(db, o, admin, (O_AWAITING,), "admin_refund"):
        db.commit()
        payments.settle(db, o)
    db.refresh(o)
    return o


def review(db: Session, buyer: m.User, o: Order, rating: int, comment: str) -> Review:
    _party(o, buyer, "buyer")
    if o.status != O_COMPLETED:
        raise conflict("INVALID_STATE", "Só dá para avaliar depois que a compra for concluída.")
    if not 1 <= rating <= 5:
        raise ResaleError("RATING_INVALID", "A nota vai de 1 a 5.")
    if db.scalar(select(Review.id).where(Review.order_id == o.id)):
        raise conflict("ALREADY_REVIEWED", "Você já avaliou este pedido.")
    r = Review(order_id=o.id, buyer_id=buyer.id, seller_id=o.seller_id, rating=rating, comment=(comment or "").strip()[:500])
    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("ALREADY_REVIEWED", "Você já avaliou este pedido.") from None
    return r
