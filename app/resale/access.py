"""Acesso comum: auditoria, troca de estado atômica (CAS) e as chaves de liberação da revenda por show."""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import models as m
from .base import BLOCK_BUY_BEFORE_SHOW_H, ResaleError, not_found, show_start, utcnow
from .models import Audit, ResaleEvent


def audit(db: Session, entity: str, entity_id: str, action: str, actor: m.User | None = None, frm: str = "", to: str = "", **meta) -> None:
    db.add(Audit(entity=entity, entity_id=entity_id, actor_id=actor.id if actor else None, action=action, from_status=frm, to_status=to, meta=meta or None))


def cas(db: Session, model, row_id: str, expected: tuple[str, ...] | str, **values) -> bool:
    """UPDATE condicional `WHERE status = :esperado`. Só quem obtém rowcount == 1 executa os efeitos da transição
    (devolver saldo, gravar no livro-razão). É isso que impede duas varreduras ou duas requisições de agirem duas vezes."""
    exp = (expected,) if isinstance(expected, str) else expected
    res = db.execute(update(model).where(model.id == row_id, model.status.in_(exp)).values(**values).execution_options(synchronize_session=False))
    return res.rowcount == 1


def get_event(db: Session, artist: m.Artist, event_id: str) -> m.Event:
    e = db.get(m.Event, event_id)
    if not e or e.artist_id != artist.id:
        raise not_found("Show não encontrado.")
    return e


def switches(db: Session, event_id: str) -> ResaleEvent | None:
    return db.get(ResaleEvent, event_id)


def event_start(e: m.Event) -> datetime | None:
    return show_start(e.date, e.time)


def open_reason(db: Session, e: m.Event, now: datetime | None = None, min_hours: int = BLOCK_BUY_BEFORE_SHOW_H) -> str:
    """'' se a revenda está aberta para este show; senão o motivo (em português)."""
    now = now or utcnow()
    sw = switches(db, e.id)
    if not sw or not (sw.ticketing_sold_out and sw.resale_open):
        return "A revenda de ingressos não está liberada para este show."
    start = event_start(e)
    if start is None:
        return "O horário do show não está definido; a revenda não pode abrir."
    if start - now < timedelta(hours=min_hours):
        return "Faltam menos de 4 horas para o show: a revenda está encerrada."
    return ""


def ensure_open(db: Session, e: m.Event, min_hours: int = BLOCK_BUY_BEFORE_SHOW_H) -> None:
    why = open_reason(db, e, min_hours=min_hours)
    if why:
        raise ResaleError("RESALE_CLOSED", why, 409)


def is_open(db: Session, e: m.Event) -> bool:
    return not open_reason(db, e)


def ticket_types(db: Session, e: m.Event) -> list[m.EventTicket]:
    return list(db.scalars(select(m.EventTicket).where(m.EventTicket.event_id == e.id).order_by(m.EventTicket.position)))
