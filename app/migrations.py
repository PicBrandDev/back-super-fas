"""Atualiza o banco na subida da API (sem apagar dados).

1. Cria as tabelas que faltam.
2. Acrescenta colunas novas em tabelas que já existiam.
3. Converte os dados para o modelo de fã clubes:
   - todo cantor ganha o fã clube master ("oficial");
   - a equipe antiga do cantor (artist_admins) vira a equipe do master (o primeiro é o dono);
   - posts da galera, roleta do PicKup e fãs passam a ser do fã clube master.
4. Cria nas vitrines de cada cantor as que faltam de DEFAULT_AD_SLOTS (ex.: os anúncios dentro do app)
   e atualiza o "onde" da vitrine do Mural se ainda for o texto padrão antigo.
5. Grava o módulo "resale" desligado nos cantores que ainda não têm a chave (a revenda saiu do app).

Tudo aqui pode rodar várias vezes sem efeito colateral.
Quando o esquema começar a mudar com frequência, trocar por Alembic.
"""

import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from . import models as m
from .resale import models as _resale_models  # noqa: F401  (registra as tabelas da revenda antes do create_all)
from .db import Base

log = logging.getLogger("superfas.migrations")

# tabela -> [(coluna, tipo SQL)]
NEW_COLUMNS = {
    "users": [
        ("avatar_path", "VARCHAR(255) DEFAULT ''"),
        ("zip_code", "VARCHAR(9) DEFAULT ''"),
        ("street", "VARCHAR(160) DEFAULT ''"),
        ("number", "VARCHAR(20) DEFAULT ''"),
        ("complement", "VARCHAR(80) DEFAULT ''"),
        ("neighborhood", "VARCHAR(80) DEFAULT ''"),
        ("state", "VARCHAR(2) DEFAULT ''"),
    ],
    "instagram_shares": [("track_id", "VARCHAR(20)")],
    "campaigns": [("target_city", "VARCHAR(80) DEFAULT ''"), ("target_radius_km", "INTEGER DEFAULT 0"),
        ("goal_views", "INTEGER DEFAULT 0"), ("goal_clicks", "INTEGER DEFAULT 0"), ("budget_cents", "INTEGER DEFAULT 0"),
        ("video_url", "VARCHAR(500) DEFAULT ''")],
    "ticket_purchases": [("coupon_code", "VARCHAR(30) DEFAULT ''"), ("discount_cents", "INTEGER DEFAULT 0"), ("addons", "JSON DEFAULT '[]'"),
        ("ticket_optin_at", "TIMESTAMP WITH TIME ZONE")],
    "product_purchases": [("qty", "INTEGER DEFAULT 1"), ("size", "VARCHAR(4) DEFAULT ''"), ("order_id", "VARCHAR(20)")],
    "event_packages": [("addons", "JSON DEFAULT '[]'")],
    "fandoms": [("share_code", "VARCHAR(12) DEFAULT ''")],
    "events": [("ticketing_name", "VARCHAR(60) DEFAULT ''"), ("ticketing_url", "VARCHAR(500) DEFAULT ''")],
    "fan_clubs": [("avatar_path", "VARCHAR(255) DEFAULT ''")],
    "posts": [("club_id", "VARCHAR(20)"), ("views", "INTEGER DEFAULT 0"), ("image_path", "VARCHAR(255) DEFAULT ''")],
    "tracks": [("views", "INTEGER DEFAULT 0")],
    "spin_credits": [("club_id", "VARCHAR(20)"), ("prize_id", "VARCHAR(20)")],
    "rewards": [("prize_id", "VARCHAR(20)")],
    "prizes": [("stock", "INTEGER"), ("club_id", "VARCHAR(20)"), ("kind", "VARCHAR(12) DEFAULT ''"), ("percent", "INTEGER DEFAULT 0"), ("instructions", "VARCHAR(200) DEFAULT ''")],
    "ad_slots": [("club_id", "VARCHAR(20)")],
    "resale_orders": [("transfer_to_enc", "VARCHAR(600) DEFAULT ''")],
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
        _pickap_to_pickup(db)
        _to_fan_clubs(db)
        _default_ad_slots(db)
        _packages_without_photo_option(db)
        _resale_module_off(db)


def _pickap_to_pickup(db: Session) -> None:
    """O módulo PicKap virou PicKup (grafia certa de pick-up, o toca-discos): troca a key das vitrines
    ("pickap", "pickap_video", "pickap_resgate", "{clube}.pickap"), o módulo do cantor e os textos gravados.
    Roda antes de _default_ad_slots para não criar vitrines novas ao lado das antigas."""

    def fix(s: str) -> str:
        return s.replace("PicKap", "PicKup").replace("pickap", "pickup") if s else s

    changed = False
    for artist in db.scalars(select(m.Artist)):
        mods = artist.modules or {}
        if "pickap" in mods:
            mods = dict(mods)
            mods.setdefault("pickup", mods["pickap"])
            del mods["pickap"]
            artist.modules = mods
            changed = True
        keys = {s.key for s in artist.ad_slots}
        for s in artist.ad_slots:
            if "pickap" in s.key:
                if fix(s.key) in keys:
                    log.warning("Vitrine %s.%s ficou com a key antiga: %s já existe", artist.slug, s.key, fix(s.key))
                    continue
                s.key = fix(s.key)
                changed = True
            for col in ("name", "where", "format"):
                if "PicKap" in (getattr(s, col) or ""):
                    setattr(s, col, fix(getattr(s, col)))
                    changed = True
    for c in db.scalars(select(m.Coupon).where(m.Coupon.source.contains("PicKap"))):
        c.source = fix(c.source)
        changed = True
    for p in db.scalars(select(m.Post).where(m.Post.official.is_(True))):
        if "PicKap" in (p.text or "") or "pickap" in (p.url or ""):
            p.text, p.url = fix(p.text), fix(p.url)
            changed = True
    for perk in db.scalars(select(m.MemberPerk)):
        if "PicKap" in (perk.title or "") or "PicKap" in (perk.sub or ""):
            perk.title, perk.sub = fix(perk.title), fix(perk.sub)
            changed = True
    if changed:
        db.commit()
        log.warning("PicKap renomeado para PicKup nos dados gravados")


def _resale_module_off(db: Session) -> None:
    """A revenda saiu do app e fica escondida: cantores sem a chave "resale" nos módulos ganham o módulo desligado.
    Quem já tem a chave (ligada ou desligada no admin) fica como está."""
    changed = False
    for artist in db.scalars(select(m.Artist)):
        mods = artist.modules or {}
        if "resale" not in mods:
            artist.modules = {**mods, "resale": False}
            changed = True
            log.warning("Módulo resale desligado: %s", artist.slug)
    if changed:
        db.commit()


def _packages_without_photo_option(db: Session) -> None:
    """O Photo Finder vem em todos os pacotes: sai a opção "com Photo Finder" (o pacote só dela é apagado e as
    opções antigas viram "selo"), e pacotes sem a lista de experiências (addons) passam a ter lista vazia."""
    changed = False
    for p in db.scalars(select(m.EventPackage)):
        if p.addons is None:
            p.addons = []
            changed = True
        items = list(p.items or [])
        if items and all(i.get("kind") == "photo" for i in items):
            db.delete(p)
            changed = True
        elif any(i.get("kind") == "photo" for i in items):
            p.items = [{**i, "kind": "seal", "label": i["label"].replace(" + Photo Finder", "")} if i.get("kind") == "photo" else i for i in items]
            changed = True
    if changed:
        db.commit()


def _default_ad_slots(db: Session) -> None:
    """Cantores antigos ganham as vitrines padrão que faltam (no fim da lista), sem mexer nas que já existem."""
    from .defaults import CLUB_AD_SLOTS, DEFAULT_AD_SLOTS, MURAL_WHERE, OLD_MURAL_WHERE

    for artist in db.scalars(select(m.Artist)):
        env = [s for s in artist.ad_slots if s.club_id is None]
        keys = {s.key for s in artist.ad_slots}
        pos = max((s.position for s in env), default=-1) + 1
        for key, name, where, fmt, top, height in DEFAULT_AD_SLOTS:
            if key in keys:
                continue
            db.add(
                m.AdSlot(
                    artist_id=artist.id, key=key, name=name, where=where, format=fmt,
                    diagram_top=top, diagram_height=height, position=pos,
                )
            )
            pos += 1
            log.warning("Vitrine criada: %s.%s", artist.slug, key)
        for s in env:
            if s.key == "mural" and s.where == OLD_MURAL_WHERE:
                s.where = MURAL_WHERE
        # Fã clubes antigos ganham as vitrines de clube que faltam.
        for club in artist.clubs:
            have = {s.key for s in artist.ad_slots if s.club_id == club.id}
            cpos = max((s.position for s in artist.ad_slots if s.club_id == club.id), default=-1) + 1
            for key, name, where, fmt, top, height in CLUB_AD_SLOTS:
                if f"{club.slug}.{key}" in have:
                    continue
                db.add(
                    m.AdSlot(
                        artist_id=artist.id, club_id=club.id, key=f"{club.slug}.{key}", name=name, where=where, format=fmt,
                        diagram_top=top, diagram_height=height, position=cpos,
                    )
                )
                cpos += 1
                log.warning("Vitrine de clube criada: %s.%s.%s", artist.slug, club.slug, key)
    db.commit()


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
