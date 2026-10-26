"""Revenda de ingressos (admin do ambiente): liberar shows, taxa, aprovar provas, decidir disputas e consultar pedidos e livro-razão."""

import json
from datetime import date

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from .. import models as m
from ..resale import access, listings, orders, private_uploads, trust, views
from ..resale.base import L_LIVE, L_PENDING, ResaleError, aware, decrypt, not_found, utcnow
from ..resale.models import Audit, Dispute, LedgerEntry, Listing, Order, Proof, ResaleEvent, ResaleSetting, Review
from ..resale.schemas import (
    AdminDisputeOut,
    AdminEventIn,
    AdminEventOut,
    AdminListingOut,
    DecideIn,
    LedgerOut,
    OrderOut,
    RejectIn,
    SettingsIn,
    SettingsOut,
)
from ..schemas import br_date
from ..security import DB, CurrentUser, ManagedArtist

router = APIRouter(tags=["Revenda de ingressos · admin"])
base = "/artists/{slug}/resale/admin"


# ---------------------------------------------------------------- taxa


@router.get(f"{base}/settings", response_model=SettingsOut)
def get_settings_(artist: ManagedArtist, db: DB):
    return SettingsOut(fee_bps=orders.fee_bps(db, artist.id))


@router.put(f"{base}/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, artist: ManagedArtist, user: CurrentUser, db: DB):
    """Taxa da intermediação em basis points (100 = 1%), descontada do vendedor. Vale só para pedidos novos."""
    s = db.get(ResaleSetting, artist.id)
    if not s:
        s = ResaleSetting(artist_id=artist.id)
        db.add(s)
    before, s.fee_bps, s.updated_by = s.fee_bps or 0, body.fee_bps, user.id
    access.audit(db, "setting", artist.id, "fee_changed", user, str(before), str(body.fee_bps))
    db.commit()
    return SettingsOut(fee_bps=s.fee_bps)


# ---------------------------------------------------------------- shows liberados


def _admin_event(db, e: m.Event) -> AdminEventOut:
    sw = access.switches(db, e.id)
    counts = dict(db.execute(select(Listing.status, func.count(Listing.id)).where(Listing.event_id == e.id).group_by(Listing.status)).all())
    return AdminEventOut(
        id=e.id, date=e.date, city=e.city, venue=e.venue, time=e.time, time_readable=access.event_start(e) is not None,
        ticketing_sold_out=bool(sw and sw.ticketing_sold_out), resale_open=bool(sw and sw.resale_open), is_open=access.is_open(db, e),
        pending_listings=counts.get(L_PENDING, 0), live_listings=counts.get(L_LIVE, 0),
    )


@router.get(f"{base}/events", response_model=list[AdminEventOut])
def admin_events(artist: ManagedArtist, db: DB):
    q = select(m.Event).where(m.Event.artist_id == artist.id, m.Event.date >= date.today()).order_by(m.Event.date)
    return [_admin_event(db, e) for e in db.scalars(q)]


@router.put(f"{base}/events/{{event_id}}", response_model=AdminEventOut)
def admin_set_event(event_id: str, body: AdminEventIn, artist: ManagedArtist, user: CurrentUser, db: DB):
    """As duas chaves do show: 'esgotou na ticketeira' e 'liberar revenda'. Nada abre sozinho."""
    e = access.get_event(db, artist, event_id)
    if body.resale_open:
        if not body.ticketing_sold_out:
            raise ResaleError("NOT_SOLD_OUT", "Só dá para liberar a revenda depois de marcar que os ingressos esgotaram na ticketeira oficial.")
        if access.event_start(e) is None:
            raise ResaleError("TIME_UNREADABLE", "Defina o horário do show (ex.: 22h) antes de liberar a revenda.")
        if e.date < date.today():
            raise ResaleError("EVENT_PAST", "Este show já passou.")
    sw = access.switches(db, e.id)
    if not sw:
        sw = ResaleEvent(event_id=e.id, artist_id=artist.id)
        db.add(sw)
    was = bool(sw.resale_open)
    sw.ticketing_sold_out, sw.resale_open = body.ticketing_sold_out, body.resale_open
    if body.resale_open and not was:
        sw.opened_by, sw.opened_at = user.id, utcnow()
    access.audit(db, "event", e.id, "resale_switch", user, str(was), str(body.resale_open), sold_out=body.ticketing_sold_out)
    db.commit()
    return _admin_event(db, e)


# ---------------------------------------------------------------- análise dos anúncios


def _codes(proof: Proof | None) -> list[str]:
    """Códigos decifrados; um dado ilegível (chave trocada) não pode derrubar a fila inteira do admin."""
    if not proof:
        return []
    try:
        return json.loads(decrypt(proof.codes_enc))
    except ResaleError:
        return []


def _admin_listing(db, artist: m.Artist, li: Listing) -> AdminListingOut:
    proof = db.get(Proof, li.id)
    e = db.get(m.Event, li.event_id)
    hist = [
        {"at": aware(a.at).isoformat(), "action": a.action, "from": a.from_status, "to": a.to_status, "actorId": a.actor_id, "meta": a.meta or {}}
        for a in db.scalars(select(Audit).where(Audit.entity == "listing", Audit.entity_id == li.id).order_by(Audit.at))
    ]
    return AdminListingOut(
        id=li.id, status=li.status, event_id=li.event_id, event_city=e.city, ticket_label=li.ticket_label, face_cents=li.face_cents, qty_total=li.qty_total,
        qty_available=li.qty_available, unit_price_cents=li.unit_price_cents, review_reason=li.review_reason, attempts=li.attempts,
        seller=trust.sellers(db, artist, [li.seller_id])[li.seller_id], codes=_codes(proof),
        proof_mime=proof.mime if proof else "", proof_url=f"/artists/{artist.slug}/resale/admin/listings/{li.id}/proof" if proof else "",
        verifier_status=proof.verifier_status if proof else "unknown", verifier_detail=proof.verifier_detail if proof else "", history=hist,
        created_at=br_date(li.created_at.date()),
    )


def _listing(db, artist: m.Artist, listing_id: str) -> Listing:
    return listings.get_listing(db, artist, listing_id)


@router.get(f"{base}/listings", response_model=list[AdminListingOut])
def admin_listings(artist: ManagedArtist, db: DB, status: str | None = None):
    q = select(Listing).where(Listing.artist_id == artist.id)
    if status:
        q = q.where(Listing.status == status)
    return [_admin_listing(db, artist, li) for li in db.scalars(q.order_by(Listing.created_at))]


@router.get(f"{base}/listings/{{listing_id}}", response_model=AdminListingOut)
def admin_listing(listing_id: str, artist: ManagedArtist, db: DB):
    return _admin_listing(db, artist, _listing(db, artist, listing_id))


@router.get(f"{base}/listings/{{listing_id}}/proof")
def admin_proof(listing_id: str, artist: ManagedArtist, db: DB):
    """Baixa a prova do ingresso (pasta privada; só admin do ambiente)."""
    li = _listing(db, artist, listing_id)
    proof = db.get(Proof, li.id)
    if not proof:
        raise not_found("Prova não encontrada.")
    ext = private_uploads.sniff(private_uploads.proof_path(proof.file_path).read_bytes()[:16])
    return FileResponse(
        private_uploads.proof_path(proof.file_path), media_type=proof.mime, filename=f"prova-{li.id}{ext[1] if ext else ''}",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}, content_disposition_type="attachment",
    )


@router.post(f"{base}/listings/{{listing_id}}/approve", response_model=AdminListingOut)
def admin_approve(listing_id: str, artist: ManagedArtist, user: CurrentUser, db: DB):
    return _admin_listing(db, artist, listings.approve(db, user, _listing(db, artist, listing_id)))


@router.post(f"{base}/listings/{{listing_id}}/reject", response_model=AdminListingOut)
def admin_reject(listing_id: str, body: RejectIn, artist: ManagedArtist, user: CurrentUser, db: DB):
    return _admin_listing(db, artist, listings.reject(db, user, _listing(db, artist, listing_id), body.reason))


# ---------------------------------------------------------------- pedidos, livro-razão, disputas


@router.get(f"{base}/orders", response_model=list[OrderOut])
def admin_orders(artist: ManagedArtist, db: DB, status: str | None = None):
    orders.sweep(db, artist_id=artist.id)  # só os prazos deste ambiente
    q = select(Order).where(Order.artist_id == artist.id)
    if status:
        q = q.where(Order.status == status)
    return views.orders_out(db, artist, list(db.scalars(q.order_by(Order.created_at.desc()).limit(200))), None)


@router.get(f"{base}/ledger", response_model=list[LedgerOut])
def admin_ledger(artist: ManagedArtist, db: DB, orderId: str | None = None):
    """Livro-razão (somente leitura) do ambiente ou de um pedido."""
    q = select(LedgerEntry).join(Order, Order.id == LedgerEntry.order_id).where(Order.artist_id == artist.id)
    if orderId:
        q = q.where(LedgerEntry.order_id == orderId)
    return [LedgerOut.model_validate(e) for e in db.scalars(q.order_by(LedgerEntry.created_at))]


@router.post(f"{base}/orders/{{order_id}}/refund", response_model=OrderOut)
def admin_refund(order_id: str, artist: ManagedArtist, user: CurrentUser, db: DB):
    """Reembolsa um pedido pago que o vendedor não transferiu."""
    o = orders.admin_refund(db, user, orders.get_order(db, artist, order_id), "")
    return views.order_out(db, artist, o, None)


def _admin_dispute(db, artist: m.Artist, d: Dispute) -> AdminDisputeOut:
    o = db.get(Order, d.order_id)
    return AdminDisputeOut(
        id=d.id, order_id=d.order_id, status=d.status, reason_code=d.reason_code, description=d.description, seller_reply=d.seller_reply,
        resolution=d.resolution, decision_note=d.decision_note, created_at=br_date(d.created_at.date()), order=views.order_out(db, artist, o, None),
    )


@router.get(f"{base}/disputes", response_model=list[AdminDisputeOut])
def admin_disputes(artist: ManagedArtist, db: DB, status: str = "open"):
    """Fila de disputas, das mais antigas para as mais novas."""
    q = select(Dispute).join(Order, Order.id == Dispute.order_id).where(Order.artist_id == artist.id, Dispute.status == status).order_by(Dispute.created_at)
    return [_admin_dispute(db, artist, d) for d in db.scalars(q)]


@router.get(f"{base}/disputes/{{dispute_id}}", response_model=AdminDisputeOut)
def admin_dispute(dispute_id: str, artist: ManagedArtist, db: DB):
    d = db.get(Dispute, dispute_id)
    if not d or db.get(Order, d.order_id).artist_id != artist.id:
        raise not_found("Disputa não encontrada.")
    return _admin_dispute(db, artist, d)


@router.post(f"{base}/disputes/{{dispute_id}}/decide", response_model=AdminDisputeOut)
def admin_decide(dispute_id: str, body: DecideIn, artist: ManagedArtist, user: CurrentUser, db: DB):
    """Reembolsa o comprador ('refund') ou libera ao vendedor ('release'). Quem é parte do pedido não decide."""
    d = db.get(Dispute, dispute_id)
    if not d or db.get(Order, d.order_id).artist_id != artist.id:
        raise not_found("Disputa não encontrada.")
    orders.decide(db, user, db.get(Order, d.order_id), body.decision, body.note)
    db.refresh(d)
    return _admin_dispute(db, artist, d)


@router.post(f"{base}/reviews/{{review_id}}/hide")
def admin_hide_review(review_id: str, artist: ManagedArtist, user: CurrentUser, db: DB):
    """Oculta uma avaliação abusiva (ela sai da média e da lista pública)."""
    r = db.get(Review, review_id)
    o = db.get(Order, r.order_id) if r else None
    if not r or not o or o.artist_id != artist.id:
        raise not_found("Avaliação não encontrada.")
    r.hidden = True
    access.audit(db, "order", o.id, "review_hidden", user)
    db.commit()
    return {"ok": True}
