"""Ambiente de demonstração: dá ao fã, sozinho, um ingresso com Photo Finder nos shows que já aconteceram.

Só funciona com DEMO_PHOTO_TICKET=true. Serve para testar o Photo Finder sem precisar comprar o pacote antes.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .defaults import ADDON_LABELS

FALLBACK = ("Transfer ida e volta", "Caravana Vintage", 9000)


def _ensure_past_event(db: Session, artist: m.Artist) -> None:
    """Sem nenhum show que já aconteceu o Photo Finder não abre; na demonstração cria um (Campinas, três semanas atrás)."""
    if any(e.date < date.today() for e in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id))):
        return
    db.add(
        m.Event(
            artist_id=artist.id, date=date.today() - timedelta(days=21), city="Campinas", venue="Arena Campinas", time="23h",
            doors_open="21h", age_rating="18+", status="on_sale",
        )
    )
    db.flush()


def ensure_photo_tickets(db: Session, artist: m.Artist, user: m.User) -> None:
    """Cria, se faltar, o ingresso com Photo Finder do usuário em cada show passado. Não faz nada com a opção desligada."""
    if not get_settings().demo_photo_ticket or user.role not in (m.ROLE_FAN, m.ROLE_ARTIST_ADMIN):
        return
    created = False
    _ensure_past_event(db, artist)
    for ev in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id)):
        if ev.date >= date.today():
            continue
        if db.scalar(select(m.TicketPurchase.id).where(m.TicketPurchase.user_id == user.id, m.TicketPurchase.event_id == ev.id)):
            continue
        label, agency, price = FALLBACK
        pkg_name = "Pacote com Photo Finder"
        for pkg in db.scalars(select(m.EventPackage).where(m.EventPackage.event_id == ev.id)):
            offer = next(iter(pkg.addons or []), None)
            if offer:
                label, price = ADDON_LABELS.get(offer["key"], offer["key"]), int(offer.get("price_cents", price))
                agency, pkg_name, addons = pkg.agency.name, pkg.name, [offer["key"]]
                break
        else:
            addons = ["transfer"]
        db.add(
            m.TicketPurchase(
                artist_id=artist.id, user_id=user.id, event_id=ev.id, package_name=pkg_name, agency_name=agency, label=label,
                kind="experience", addons=addons, price_cents=price,
            )
        )
        created = True
    if created:
        db.commit()
