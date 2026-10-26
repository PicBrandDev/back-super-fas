"""Anúncios de revenda: criação com prova do ingresso, reenvio, cancelamento e a aprovação do admin do ambiente."""

import json
import re
from datetime import timedelta

from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from . import access, identity, private_uploads
from .base import (
    L_CANCELLED,
    L_LIVE,
    L_PENDING,
    L_REJECTED,
    MAX_ATTEMPTS,
    MAX_LISTINGS_PER_HOUR,
    O_ACTIVE,
    O_COMPLETED,
    ResaleError,
    conflict,
    encrypt,
    forbidden,
    not_found,
    pepper_hash,
    utcnow,
)
from .models import Listing, Order, Proof, TicketCode
from .verifier import get_verifier, summarize

MAX_QTY = 10


def normalize_codes(raw: list[str], qty: int) -> list[str]:
    """Um código por ingresso: sem espaços, em maiúsculas, 4 a 64 caracteres, sem repetir dentro do anúncio."""
    codes = [re.sub(r"\s+", "", c or "").upper() for c in raw]
    if len(codes) != qty:
        raise ResaleError("CODES_COUNT", f"Informe o código de cada ingresso: são {qty} ingresso(s) e {len(codes)} código(s).")
    if any(not 4 <= len(c) <= 64 for c in codes):
        raise ResaleError("CODE_INVALID", "Cada código de ingresso precisa ter de 4 a 64 caracteres.")
    if len(set(codes)) != len(codes):
        raise ResaleError("CODES_REPEATED", "Há códigos repetidos no anúncio.")
    return codes


def get_listing(db: Session, artist: m.Artist, listing_id: str) -> Listing:
    li = db.get(Listing, listing_id)
    if not li or li.artist_id != artist.id:
        raise not_found("Anúncio não encontrado.")
    return li


def _check_proof_and_codes(db: Session, event_id: str, sha256: str, codes: list[str], own_listing_id: str | None) -> None:
    live = (L_PENDING, L_LIVE)
    q = select(Proof.listing_id).join(Listing, Listing.id == Proof.listing_id).where(
        Listing.event_id == event_id, Listing.status.in_(live), Proof.sha256 == sha256
    )
    if own_listing_id:
        q = q.where(Proof.listing_id != own_listing_id)
    if db.scalar(q):
        raise conflict("PROOF_DUPLICATE", "Este arquivo já foi usado em outro anúncio deste show.")
    hashes = [pepper_hash(f"{event_id}:{c}") for c in codes]
    q2 = select(TicketCode.id).where(TicketCode.event_id == event_id, TicketCode.active.is_(True), TicketCode.code_hash.in_(hashes))
    if own_listing_id:
        q2 = q2.where(TicketCode.listing_id != own_listing_id)
    if db.scalar(q2):
        raise conflict("CODE_DUPLICATE", "Um desses ingressos já está anunciado.")


def _store_codes(db: Session, event_id: str, listing_id: str, codes: list[str]) -> None:
    for c in codes:
        db.add(TicketCode(event_id=event_id, listing_id=listing_id, code_hash=pepper_hash(f"{event_id}:{c}"), active=True))


def _deactivate_codes(db: Session, listing_id: str) -> None:
    db.execute(update(TicketCode).where(TicketCode.listing_id == listing_id).values(active=False))


def _verify(db: Session, e: m.Event, label: str, codes: list[str], seller: m.User, proof: Proof) -> None:
    ver = get_verifier()
    res = summarize([ver.verify(e, label, c, seller) for c in codes])
    proof.verifier_status, proof.verifier_detail = res.status, res.detail[:200]


async def create(db: Session, artist: m.Artist, seller: m.User, e: m.Event, ticket_id: str, qty: int, unit_price: int, raw_codes: list[str], file: UploadFile | None) -> Listing:
    _, can_sell, missing = identity.eligibility(db, artist, seller)
    if not can_sell:
        raise forbidden("NOT_ELIGIBLE", "Complete o cadastro para vender: " + ", ".join(missing) + ".")
    access.ensure_open(db, e)
    if not 1 <= qty <= MAX_QTY:
        raise ResaleError("QTY_INVALID", f"Anuncie de 1 a {MAX_QTY} ingressos por vez.")
    t = db.get(m.EventTicket, ticket_id)
    if not t or t.event_id != e.id:
        raise not_found("Tipo de ingresso não encontrado neste show.")
    if not t.price_cents or t.price_cents <= 0:
        raise ResaleError("FACE_UNKNOWN", "Este tipo de ingresso não tem valor de face definido; não dá para anunciar.")
    if not 0 < unit_price <= t.price_cents:
        raise ResaleError("PRICE_ABOVE_FACE", f"O preço por ingresso não pode passar do valor de face (R$ {t.price_cents / 100:.2f}).".replace(".", ","))
    codes = normalize_codes(raw_codes, qty)
    since = utcnow() - timedelta(hours=1)
    recent = db.scalar(select(func.count(Listing.id)).where(Listing.seller_id == seller.id, Listing.created_at >= since)) or 0
    if recent >= MAX_LISTINGS_PER_HOUR:
        raise ResaleError("RATE_LIMIT", "Você criou muitos anúncios na última hora. Tente de novo mais tarde.", 429)

    name, mime, sha = await private_uploads.save_proof(file)
    try:
        _check_proof_and_codes(db, e.id, sha, codes, None)
        li = Listing(
            artist_id=artist.id, event_id=e.id, event_ticket_id=t.id, seller_id=seller.id, ticket_label=t.label, face_cents=t.price_cents,
            qty_total=qty, qty_available=qty, unit_price_cents=unit_price, status=L_PENDING,
        )
        db.add(li)
        db.flush()
        proof = Proof(listing_id=li.id, file_path=name, mime=mime, sha256=sha, codes_enc=encrypt(json.dumps(codes)))
        db.add(proof)
        _verify(db, e, t.label, codes, seller, proof)
        _store_codes(db, e.id, li.id, codes)
        access.audit(db, "listing", li.id, "created", seller, to=L_PENDING, qty=qty, unit_price_cents=unit_price)
        db.commit()
    except ResaleError:
        db.rollback()
        (private_uploads.private_dir() / name).unlink(missing_ok=True)
        raise
    except IntegrityError:  # a trava do banco pegou um código repetido que passou na checagem (duas contas ao mesmo tempo)
        db.rollback()
        (private_uploads.private_dir() / name).unlink(missing_ok=True)
        raise conflict("CODE_DUPLICATE", "Um desses ingressos já está anunciado.") from None
    except Exception:  # erro inesperado: não deixa arquivo órfão na pasta privada
        db.rollback()
        (private_uploads.private_dir() / name).unlink(missing_ok=True)
        raise
    return li


async def resubmit(db: Session, artist: m.Artist, seller: m.User, li: Listing, raw_codes: list[str], file: UploadFile | None) -> Listing:
    if li.seller_id != seller.id:
        raise forbidden("NOT_OWNER", "Este anúncio não é seu.")
    if li.status != L_REJECTED:
        raise conflict("INVALID_STATE", "Só dá para reenviar a prova de um anúncio rejeitado.")
    if li.attempts >= MAX_ATTEMPTS:
        raise conflict("ATTEMPTS_EXHAUSTED", "Você já usou as 3 tentativas de envio deste anúncio. Crie um anúncio novo.")
    e = db.get(m.Event, li.event_id)
    access.ensure_open(db, e)
    codes = normalize_codes(raw_codes, li.qty_total)
    name, mime, sha = await private_uploads.save_proof(file)
    try:
        _check_proof_and_codes(db, e.id, sha, codes, li.id)
        proof = db.get(Proof, li.id)
        old = proof.file_path
        proof.file_path, proof.mime, proof.sha256, proof.codes_enc, proof.updated_at = name, mime, sha, encrypt(json.dumps(codes)), utcnow()
        _verify(db, e, li.ticket_label, codes, seller, proof)
        db.execute(update(TicketCode).where(TicketCode.listing_id == li.id).values(active=False))
        _store_codes(db, e.id, li.id, codes)
        if not access.cas(db, Listing, li.id, L_REJECTED, status=L_PENDING, attempts=li.attempts + 1, review_reason=""):
            raise conflict("INVALID_STATE", "O anúncio mudou de situação. Atualize a página.")
        access.audit(db, "listing", li.id, "resubmitted", seller, L_REJECTED, L_PENDING)
        db.commit()
    except ResaleError:
        db.rollback()
        (private_uploads.private_dir() / name).unlink(missing_ok=True)
        raise
    except IntegrityError:
        db.rollback()
        (private_uploads.private_dir() / name).unlink(missing_ok=True)
        raise conflict("CODE_DUPLICATE", "Um desses ingressos já está anunciado.") from None
    except Exception:
        db.rollback()
        (private_uploads.private_dir() / name).unlink(missing_ok=True)
        raise
    (private_uploads.private_dir() / old).unlink(missing_ok=True)
    db.refresh(li)
    return li


def cancel(db: Session, seller: m.User, li: Listing) -> Listing:
    if li.seller_id != seller.id:
        raise forbidden("NOT_OWNER", "Este anúncio não é seu.")
    if li.status == L_CANCELLED:
        return li  # idempotente
    if li.status not in (L_PENDING, L_REJECTED, L_LIVE):
        raise conflict("INVALID_STATE", "Este anúncio não pode mais ser cancelado.")
    active = db.scalar(select(func.count(Order.id)).where(Order.listing_id == li.id, Order.status.in_(O_ACTIVE))) or 0
    if active:
        raise conflict("HAS_ACTIVE_ORDERS", "Há compras em andamento neste anúncio. Conclua-as antes de cancelar.")
    frm = li.status
    if not access.cas(db, Listing, li.id, (L_PENDING, L_REJECTED, L_LIVE), status=L_CANCELLED):
        raise conflict("INVALID_STATE", "O anúncio mudou de situação. Atualize a página.")
    # uma reserva pode ter entrado entre a checagem acima e a troca de estado: confere de novo e desfaz se houver
    db.flush()
    if db.scalar(select(func.count(Order.id)).where(Order.listing_id == li.id, Order.status.in_(O_ACTIVE))):
        access.cas(db, Listing, li.id, L_CANCELLED, status=frm)
        db.commit()
        raise conflict("HAS_ACTIVE_ORDERS", "Entrou uma compra neste anúncio agora. Conclua-a antes de cancelar.")
    # com venda já concluída, os códigos ficam bloqueados: não dá para saber quais ingressos já foram entregues
    sold = db.scalar(select(func.count(Order.id)).where(Order.listing_id == li.id, Order.status == O_COMPLETED)) or 0
    if not sold:
        _deactivate_codes(db, li.id)
    access.audit(db, "listing", li.id, "cancelled", seller, frm, L_CANCELLED)
    db.commit()
    db.refresh(li)
    return li


def _no_self_review(admin: m.User, li: Listing) -> None:
    if li.seller_id == admin.id:
        raise forbidden("CONFLICT_OF_INTEREST", "Você é o vendedor deste anúncio: outro admin precisa analisá-lo.")


def approve(db: Session, admin: m.User, li: Listing) -> Listing:
    _no_self_review(admin, li)
    if li.status == L_LIVE:
        return li
    if li.status != L_PENDING:
        raise conflict("INVALID_STATE", "Só dá para aprovar um anúncio em análise.")
    access.ensure_open(db, db.get(m.Event, li.event_id))
    t = db.get(m.EventTicket, li.event_ticket_id) if li.event_ticket_id else None
    if t and t.price_cents and li.unit_price_cents > t.price_cents:
        raise conflict("PRICE_ABOVE_FACE", "O preço deste anúncio está acima do valor de face atual. Rejeite e peça um novo anúncio.")
    if not access.cas(db, Listing, li.id, L_PENDING, status=L_LIVE, reviewed_by=admin.id, reviewed_at=utcnow(), review_reason=""):
        raise conflict("INVALID_STATE", "O anúncio mudou de situação. Atualize a página.")
    access.audit(db, "listing", li.id, "approved", admin, L_PENDING, L_LIVE)
    db.commit()
    db.refresh(li)
    return li


def reject(db: Session, admin: m.User, li: Listing, reason: str) -> Listing:
    _no_self_review(admin, li)
    reason = (reason or "").strip()
    if not reason:
        raise ResaleError("REASON_REQUIRED", "Explique o motivo da rejeição.")
    if li.status != L_PENDING:
        raise conflict("INVALID_STATE", "Só dá para rejeitar um anúncio em análise.")
    if not access.cas(db, Listing, li.id, L_PENDING, status=L_REJECTED, reviewed_by=admin.id, reviewed_at=utcnow(), review_reason=reason[:300]):
        raise conflict("INVALID_STATE", "O anúncio mudou de situação. Atualize a página.")
    _deactivate_codes(db, li.id)  # os códigos voltam a poder ser anunciados
    access.audit(db, "listing", li.id, "rejected", admin, L_PENDING, L_REJECTED, reason=reason[:300])
    db.commit()
    db.refresh(li)
    return li
