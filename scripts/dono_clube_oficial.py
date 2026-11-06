"""Dá um dono ao fã clube oficial (master) de Departamento e Anitta, como o Vintage tem admin@vintage.com.br.

Idempotente: quem já tem dono não muda. Imprime a senha provisória só quando cria a conta (troca no 1º acesso).
Para outro e-mail, edite DONOS ou convide pelo admin master (/admin/fas-clubes).

Local:    PYTHONPATH=. python scripts/dono_clube_oficial.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/dono_clube_oficial.py
"""

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.routers.clubs import invite_staff

DONOS = {
    "departamento": ("admin@departamento.com.br", "Admin Departamento"),
    "anitta": ("admin@anitta.com.br", "Admin Anitta"),
}

with SessionLocal() as db:
    for slug, (email, nome) in DONOS.items():
        art = db.scalar(select(m.Artist).where(m.Artist.slug == slug))
        master = art and db.scalar(select(m.FanClub).where(m.FanClub.artist_id == art.id, m.FanClub.is_master.is_(True)))
        if not master:
            print(f"{slug}: sem fã clube oficial, pulei")
            continue
        if any(st.role == m.STAFF_OWNER for st in master.staff):
            print(f"{slug}: já tem dono")
            continue
        inv = invite_staff(db, master, email, nome, m.STAFF_OWNER)
        print(f"{slug}: dono {inv.email}" + (f" | senha provisória: {inv.temp_password}" if inv.temp_password else " (conta já existia)"))
    db.commit()
