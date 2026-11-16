"""Cria os fã clubes de RJ, SP e RS do João Gomes (com dono e alguns fãs), sem mexer no que já existe.

O Forrozeiros SP já vem do popular_joao_gomes.py: aqui ele só é conferido. Cada clube novo ganha um dono (conta nova de admin do clube)
e fãs que já existem no banco. Pode rodar de novo: clube que já existe (mesmo nome) é pulado.

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/clubes_joao_gomes.py
Local:    PYTHONPATH=. python scripts/clubes_joao_gomes.py
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.routers.clubs import create_club
from app.security import hash_password, temp_password

SLUG = "joao-gomes"
rnd = random.Random(2026)
agora = datetime.now(timezone.utc)

CLUBES = [
    ("Forrozeiros RJ", "Rio de Janeiro", "Fã-clube do João no Rio: caravana pros shows e forró depois dos Arcos da Lapa.", "Léo Marques"),
    ("Forrozeiros SP", "São Paulo", "Paulistas do piseiro: ônibus pros shows e encontro antes de cada data.", "Bia Lopes"),
    ("Forrozeiros RS", "Porto Alegre", "Gaúchos no piseiro: o forró chegou no Sul e a galera se organiza pra ir junta.", "Tati Machado"),
]

with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if not art:
        raise SystemExit("Ambiente joao-gomes não encontrado: rode antes o criar_joao_gomes.py.")
    fas = list(db.scalars(select(m.User).where(m.User.role == m.ROLE_FAN).order_by(m.User.created_at)))[:40]
    senhas = []
    for nome, cidade, desc, dono in CLUBES:
        c = db.scalar(select(m.FanClub).where(m.FanClub.artist_id == art.id, m.FanClub.name == nome))
        if c:
            print(f"já existe: {nome}")
            continue
        c = create_club(db, art, nome, desc, cidade)
        email = f"dono.{c.slug}@joaogomes.example"
        u = db.scalar(select(m.User).where(m.User.email == email))
        if not u:
            senha = temp_password()
            u = m.User(email=email, name=dono, handle="@" + dono.lower().replace(" ", "."), role=m.ROLE_ARTIST_ADMIN, password_hash=hash_password(senha), city=cidade)
            db.add(u)
            db.flush()
            senhas.append((nome, email, senha))
        db.add(m.ClubStaff(club_id=c.id, user_id=u.id, role=m.STAFF_OWNER, role_label="Dono do fã clube"))
        ja = {cm.user_id for cm in db.scalars(select(m.ClubMember).where(m.ClubMember.club_id == c.id))}
        for f in rnd.sample(fas, min(12, len(fas))):
            if f.id not in ja:
                db.add(m.ClubMember(club_id=c.id, user_id=f.id, created_at=agora - timedelta(days=rnd.randint(1, 60))))
        print(f"fã clube criado: {nome} ({cidade})")
    db.commit()

if senhas:
    print("\nDonos dos fã clubes criados (anote as senhas, elas não aparecem de novo):")
    for nome, email, senha in senhas:
        print(f"  {nome:<20} {email:<42} {senha}")
print("\npronto")
