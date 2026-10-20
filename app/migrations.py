"""Atualiza o banco na subida da API (sem apagar dados).

1. Cria as tabelas que faltam.
2. Acrescenta colunas novas em tabelas que já existiam.
3. Converte os dados para o modelo de fã clubes:
   - todo cantor ganha o fã clube master ("oficial");
   - a equipe antiga do cantor (artist_admins) vira a equipe do master (o primeiro é o dono);
   - posts da galera, roleta do PicKap e fãs passam a ser do fã clube master.

Tudo aqui pode rodar várias vezes sem efeito colateral.
Quando o esquema começar a mudar com frequência, trocar por Alembic.
"""

import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from . import models as m
from .db import Base

log = logging.getLogger("superfas.migrations")

# tabela -> [(coluna, tipo SQL)]
NEW_COLUMNS = {
    "posts": [("club_id", "VARCHAR(20)")],
    "prizes": [("club_id", "VARCHAR(20)")],
    "ad_slots": [("club_id", "VARCHAR(20)")],
}


def upgrade(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in NEW_COLUMNS.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, sqltype in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"))
                    log.warning("Coluna criada: %s.%s", table, name)
        if engine.dialect.name == "postgresql":
            # A key das vitrines de fã clube ("{clube}.home") é maior que o tamanho antigo.
            conn.execute(text("ALTER TABLE ad_slots ALTER COLUMN key TYPE VARCHAR(80)"))

    with Session(engine) as db:
        _to_fan_clubs(db)


def _to_fan_clubs(db: Session) -> None:
    from .routers.clubs import create_club

    for artist in db.scalars(select(m.Artist)):
        master = db.scalar(select(m.FanClub).where(m.FanClub.artist_id == artist.id, m.FanClub.is_master.is_(True)))
        if master:
            continue
        name = artist.fan_club_name if artist.fan_club_name and not artist.fan_club_name.startswith("[") else ""
        master = create_club(db, artist, name or f"Fã clube oficial {artist.name}", is_master=True)

        # Equipe antiga do cantor -> equipe do master (o mais antigo vira dono).
        old = db.scalars(select(m.ArtistAdmin).where(m.ArtistAdmin.artist_id == artist.id).order_by(m.ArtistAdmin.created_at)).all()
        for i, a in enumerate(old):
            db.add(
                m.ClubStaff(
                    club_id=master.id,
                    user_id=a.user_id,
                    role=m.STAFF_OWNER if i == 0 else m.STAFF_HELPER,
                    role_label="Dono do fã clube" if i == 0 else (a.role_label or "Ajudante"),
                )
            )
        # Galera e Instagram, roleta e fãs -> fã clube master.
        for p in db.scalars(select(m.Post).where(m.Post.artist_id == artist.id, m.Post.club_id.is_(None), m.Post.kind != "drop")):
            p.club_id = master.id
        for p in db.scalars(select(m.Prize).where(m.Prize.artist_id == artist.id, m.Prize.club_id.is_(None))):
            p.club_id = master.id
        for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id)):
            db.add(m.ClubMember(club_id=master.id, user_id=f.user_id))
        log.warning("Fã clube master criado para %s (%d na equipe)", artist.name, len(old))
    db.commit()
