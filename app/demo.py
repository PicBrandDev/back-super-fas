"""Ambiente de demonstração: dá ao fã, sozinho, um ingresso com Photo Finder nos shows que já aconteceram.

Só funciona com DEMO_PHOTO_TICKET=true. Serve para testar o Photo Finder sem precisar comprar o pacote antes.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings

FALLBACK = ("Pista + transfer + selo + Photo Finder", "Caravana Vintage", 29000)


def ensure_photo_tickets(db: Session, artist: m.Artist, user: m.User) -> None:
    """Cria, se faltar, o ingresso com Photo Finder do usuário em cada show passado. Não faz nada com a opção desligada."""
    if not get_settings().demo_photo_ticket or user.role not in (m.ROLE_FAN, m.ROLE_ARTIST_ADMIN):
        return
    created = False
    for ev in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id)):
        if ev.date >= date.today():
            continue
        if db.scalar(select(m.TicketPurchase.id).where(m.TicketPurchase.user_id == user.id, m.TicketPurchase.event_id == ev.id, m.TicketPurchase.kind == "photo")):
            continue
        label, agency, price = FALLBACK
        pkg_name = "Pacote com Photo Finder"
        for pkg in db.scalars(select(m.EventPackage).where(m.EventPackage.event_id == ev.id)):
            item = next((i for i in (pkg.items or []) if i.get("kind") == "photo"), None)
            if item:
                label, price = item["label"], int(item.get("price_cents", price))
                agency, pkg_name = pkg.agency.name, pkg.name
                break
        db.add(m.TicketPurchase(artist_id=artist.id, user_id=user.id, event_id=ev.id, package_name=pkg_name, agency_name=agency, label=label, kind="photo", price_cents=price))
        created = True
    if created:
        db.commit()
