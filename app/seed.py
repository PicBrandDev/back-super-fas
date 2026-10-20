"""Primeira carga do banco: o fã clube Vintage Culture e uma conta de teste de cada tipo.

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
from .defaults import MODULES, VINTAGE_THEME
from .routers.master import add_default_slots
from .security import hash_password

log = logging.getLogger("superfas.seed")

SEED_ACCOUNTS = [
    # e-mail, nome, papel, @
    ("admin@superfas.dev", "Admin Master", m.ROLE_MASTER, ""),
    ("vintage@superfas.dev", "Admin Vintage Culture", m.ROLE_ARTIST_ADMIN, ""),
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
            modules={k: True for k in MODULES},
        )
        db.add(vc)
        db.flush()
        add_default_slots(db, vc)

    sponsor = m.Sponsor(email="marca@superfas.dev", brand="Marca Teste", status="active")
    db.add(sponsor)

    for email, name, role, handle in SEED_ACCOUNTS:
        user = m.User(email=email, name=name, handle=handle, role=role, password_hash=hash_password(password))
        if role == m.ROLE_SPONSOR:
            user.sponsor = sponsor
        db.add(user)
        if role == m.ROLE_ARTIST_ADMIN:
            db.add(m.ArtistAdmin(artist=vc, user=user, role_label="Dono do fã clube"))
        if role == m.ROLE_FAN:
            db.add(m.Fandom(artist=vc, user=user))

    db.commit()
    lines = "\n".join(f"    {role:<13} {email}" for email, _, role, _ in SEED_ACCOUNTS)
    shown = "(a definida em SEED_PASSWORD)" if get_settings().seed_password else password
    log.warning("Contas de teste criadas:\n%s\n    senha: %s", lines, shown)
