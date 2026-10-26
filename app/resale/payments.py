"""Pagamento com escrow: interface do provedor, provedor falso e o livro-razão (partida dobrada, só de inclusão).

O comprador paga à plataforma (hold: buyer_external -> escrow). Na conclusão o valor sai do escrow: líquido ao vendedor
(release_seller) e taxa à plataforma (fee). No reembolso volta ao comprador (refund). UNIQUE (pedido, tipo) garante que
cada movimento acontece no máximo uma vez; o lançamento nasce `pending` junto com a mudança de status e só vira `settled`
depois que o provedor confirma (padrão outbox: a varredura reprocessa os `pending`)."""

import logging
from datetime import timedelta
from typing import Protocol

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from .base import ResaleError, is_dev_db, utcnow
from .models import LedgerEntry, Order

log = logging.getLogger("superfas.resale.payments")


class PaymentProvider(Protocol):
    """`idem` é a chave de idempotência do movimento (o id do lançamento): o gateway não pode agir duas vezes com a mesma."""

    name: str

    def hold(self, order: Order, idem: str) -> str: ...  # confirma que o valor bruto está retido; devolve a referência
    def release(self, order: Order, net_cents: int, fee_cents: int, idem: str) -> str: ...  # repassa ao vendedor
    def refund(self, order: Order, idem: str) -> str: ...  # devolve o bruto ao comprador
    def verify_webhook(self, headers: dict[str, str], body: bytes) -> dict | None: ...  # {"order_id", "ref", "amount_cents"} ou None


class FakeProvider:
    """Pagamento simulado: tudo dá certo na hora. Não aceita webhook."""

    name = "fake"

    def hold(self, order: Order, idem: str) -> str:
        return f"fake-hold-{order.id}"

    def release(self, order: Order, net_cents: int, fee_cents: int, idem: str) -> str:
        return f"fake-release-{order.id}"

    def refund(self, order: Order, idem: str) -> str:
        return f"fake-refund-{order.id}"

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> dict | None:
        return None


def fake_allowed() -> bool:
    """O pagamento simulado liga sozinho no SQLite (dev/teste). Em servidor (Postgres) só com RESALE_ALLOW_FAKE_PAYMENT=true,
    para ninguém "pagar" de mentira em produção por esquecer de configurar o gateway."""
    s = get_settings()
    return is_dev_db() or s.resale_allow_fake_payment


def get_provider() -> PaymentProvider:
    name = get_settings().resale_payment_provider
    if name == "fake":
        if not fake_allowed():
            raise ResaleError("PAYMENT_NOT_CONFIGURED", "O pagamento da revenda ainda não está configurado neste ambiente.", 503)
        return FakeProvider()
    raise ResaleError("PROVIDER_UNAVAILABLE", "O provedor de pagamento não está configurado.", 503)


def is_fake() -> bool:
    return get_settings().resale_payment_provider == "fake" and fake_allowed()


# ---------------------------------------------------------------- livro-razão


def entry(db: Session, order_id: str, kind: str) -> LedgerEntry | None:
    return db.scalar(select(LedgerEntry).where(LedgerEntry.order_id == order_id, LedgerEntry.kind == kind))


def _post(db: Session, order: Order, kind: str, debit: str, credit: str, amount: int) -> LedgerEntry | None:
    """Grava o lançamento (idempotente por pedido+tipo). Valor zero (ex.: taxa 0%) não gera lançamento."""
    if amount <= 0:
        return None
    existing = entry(db, order.id, kind)
    if existing:
        return existing
    e = LedgerEntry(order_id=order.id, kind=kind, debit_account=debit, credit_account=credit, amount_cents=amount)
    db.add(e)
    db.flush()
    return e


def post_hold(db: Session, order: Order) -> None:
    _post(db, order, "hold", "buyer_external", "escrow", order.gross_cents)


def post_release(db: Session, order: Order) -> None:
    """Conclusão: do escrow, o líquido ao vendedor e a taxa à plataforma. Nunca junto com um reembolso."""
    if entry(db, order.id, "refund"):
        raise ResaleError("LEDGER_CONFLICT", "Pedido já reembolsado: não pode ser liberado ao vendedor.", 500)
    _post(db, order, "release_seller", "escrow", "seller_payable", order.seller_net_cents)
    _post(db, order, "fee", "escrow", "platform_fee", order.fee_cents)


def post_refund(db: Session, order: Order) -> None:
    if entry(db, order.id, "release_seller") or entry(db, order.id, "fee"):
        raise ResaleError("LEDGER_CONFLICT", "Pedido já liberado ao vendedor: não pode ser reembolsado.", 500)
    _post(db, order, "refund", "escrow", "buyer_external", order.gross_cents)


STALE_CLAIM = timedelta(minutes=10)  # um lançamento "processing" parado há mais que isso volta para a fila (o processo caiu)


def _claim(db: Session, e: LedgerEntry) -> bool:
    """pending -> processing de forma atômica: só um processo chama o provedor para cada lançamento."""
    now = utcnow()
    res = db.execute(
        update(LedgerEntry)
        .where(
            LedgerEntry.id == e.id,
            or_(LedgerEntry.status == "pending", and_(LedgerEntry.status == "processing", LedgerEntry.claimed_at < now - STALE_CLAIM)),
        )
        .values(status="processing", claimed_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return res.rowcount == 1


def settle(db: Session, order: Order) -> None:
    """Chama o provedor para os lançamentos pendentes do pedido e os marca `settled`. Falha (inclusive provedor mal
    configurado) deixa o lançamento `pending` para a varredura tentar de novo; NUNCA propaga o erro para quem está lendo."""
    try:
        provider = get_provider()
    except ResaleError:
        log.warning("Provedor de pagamento indisponível: lançamentos do pedido %s ficam pendentes.", order.id)
        return
    stale = utcnow() - STALE_CLAIM
    todo = db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.order_id == order.id,
            or_(LedgerEntry.status == "pending", and_(LedgerEntry.status == "processing", LedgerEntry.claimed_at < stale)),
        )
    ).all()
    for e in todo:
        if not _claim(db, e):
            continue  # outro processo assumiu
        db.refresh(e)
        try:
            if e.kind == "hold":
                ref = provider.hold(order, e.id)
            elif e.kind == "release_seller":
                ref = provider.release(order, order.seller_net_cents, order.fee_cents, e.id)
            elif e.kind == "refund":
                ref = provider.refund(order, e.id)
            else:
                ref = ""  # "fee" é movimento interno (escrow -> plataforma): não chama o provedor
            e.provider_ref, e.status = ref, "settled"
        except Exception:  # noqa: BLE001 - o provedor pode falhar de qualquer forma; volta para a fila
            log.exception("Falha do provedor ao liquidar %s do pedido %s.", e.kind, order.id)
            e.status = "pending"
        db.commit()


def escrow_balance(db: Session, order_id: str) -> int:
    """Saldo do escrow do pedido (entradas - saídas): 0 em todo pedido encerrado."""
    total = 0
    for e in db.scalars(select(LedgerEntry).where(LedgerEntry.order_id == order_id)):
        if e.credit_account == "escrow":
            total += e.amount_cents
        if e.debit_account == "escrow":
            total -= e.amount_cents
    return total
