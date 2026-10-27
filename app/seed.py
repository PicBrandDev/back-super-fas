"""Primeira carga do banco: o ambiente Vintage Culture (com o fã clube master) e uma conta de teste de cada tipo.

Só roda quando o banco está vazio (sem nenhum admin master). O conteúdo
(shows, posts, produtos…) é criado depois pelas telas de admin.
"""

import copy
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .defaults import DEFAULT_MODULES, VINTAGE_THEME
from .routers.clubs import create_club
from .routers.master import add_default_slots
from .security import hash_password

log = logging.getLogger("superfas.seed")

SEED_ACCOUNTS = [
    # e-mail, nome, papel, @
    ("admin@superfas.dev", "Admin Master", m.ROLE_MASTER, ""),
    ("vintage@superfas.dev", "Admin master Vintage Culture", m.ROLE_ARTIST_ADMIN, ""),
    ("marca@superfas.dev", "Marca Teste", m.ROLE_SPONSOR, ""),
    ("fa@superfas.dev", "Fã Teste", m.ROLE_FAN, "@fa.teste"),
]


def seed(db: Session) -> None:
    if db.scalar(select(m.User).where(m.User.role == m.ROLE_MASTER)):
        return

    password = get_settings().seed_password or secrets.token_urlsafe(10)

    vc = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
    if not vc:
        vc = m.Artist(
            slug="vintage-culture",
            name="Vintage Culture",
            fan_club_name="[Nome do fã clube]",
            instagram="@vintageculture",
            status="active",
            theme=copy.deepcopy(VINTAGE_THEME),
            member_price_cents=1690,
            brand_color="#B8461A",
            modules=dict(DEFAULT_MODULES),
        )
        db.add(vc)
        db.flush()
        add_default_slots(db, vc)
        create_club(db, vc, "Fã clube oficial Vintage Culture", "O fã clube master do Vintage Culture.", is_master=True)
    master = db.scalar(select(m.FanClub).where(m.FanClub.artist_id == vc.id, m.FanClub.is_master.is_(True)))

    sponsor = m.Sponsor(email="marca@superfas.dev", brand="Marca Teste", status="active")
    db.add(sponsor)

    for email, name, role, handle in SEED_ACCOUNTS:
        user = m.User(email=email, name=name, handle=handle, role=role, password_hash=hash_password(password))
        if role == m.ROLE_SPONSOR:
            user.sponsor = sponsor
        db.add(user)
        db.flush()
        if role == m.ROLE_ARTIST_ADMIN and master:
            # Dono do fã clube master = admin master do Vintage Culture.
            db.add(m.ClubStaff(club_id=master.id, user_id=user.id, role=m.STAFF_OWNER, role_label="Dono do fã clube"))
        if role == m.ROLE_FAN:
            db.add(m.Fandom(artist=vc, user=user))
            if master:
                db.add(m.ClubMember(club_id=master.id, user_id=user.id))

    db.commit()
    lines = "\n".join(f"    {role:<13} {email}" for email, _, role, _ in SEED_ACCOUNTS)
    shown = "(a definida em SEED_PASSWORD)" if get_settings().seed_password else password
    log.warning("Contas de teste criadas:\n%s\n    senha: %s", lines, shown)
