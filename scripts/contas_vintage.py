"""Cria (ou atualiza) as contas de acesso do ambiente Vintage Culture: o admin do ambiente, os donos dos
fã clubes e uma conta de fã. Pode rodar quantas vezes quiser: só ajusta o que falta.

No servidor (a pasta `scripts` não vai dentro do container, então o arquivo entra pela entrada padrão):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/contas_vintage.py

No seu computador:

    PYTHONPATH=. .venv/Scripts/python scripts/contas_vintage.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/contas_vintage.py          # Linux/Mac

A senha vem de CONTAS_SENHA (padrão: senha123). Troque por uma senha forte em servidor público:

    sudo docker compose exec -T -e CONTAS_SENHA='uma-senha-forte' api python - < ../back-super-fas/scripts/contas_vintage.py
"""

import os

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.routers.clubs import create_club
from app.security import hash_password

PASSWORD = os.environ.get("CONTAS_SENHA", "senha123")
ARTIST = "vintage-culture"

ADMIN = ("admin@vintage.com.br", "Admin Vintage Culture")  # dono do fã clube master = admin do ambiente
FAN = ("juliacristinalopes2607@gmail.com", "Julia Cristina Lopes")

# fã clube, cidade, descrição, e-mail do dono, nome do dono
OWNERS = [
    ("Vintage Curitiba", "Curitiba", "A galera de Curitiba: pré-baladas e caravana para os shows do sul.", "dono.curitiba@vintage.com.br", "Marcos Vieira"),
    ("Vintage BH", "Belo Horizonte", "Mineiros do house: encontros, trocas de camiseta e muito pão de queijo.", "dono.bh@vintage.com.br", "Luana Prado"),
    ("Vintage Brasília", "Brasília", "Fã clube do Planalto Central, com sorteios a cada show.", "dono.brasilia@vintage.com.br", "Thiago Nunes"),
    ("Vintage Salvador", "Salvador", "Baianos no mesmo ritmo: festas, fotos dos shows e caravanas.", "dono.salvador@vintage.com.br", "Aline Souza"),
    ("Vintage Porto Alegre", "Porto Alegre", "Gaúchos fãs do Vintage Culture: churrasco, house e muita resenha.", "dono.poa@vintage.com.br", "Gustavo Pereira"),
]


def user(db, email: str, name: str, role: str) -> m.User:
    """Acha a conta pelo e-mail (ou cria) e deixa a senha e o papel como combinado."""
    u = db.scalar(select(m.User).where(m.User.email == email))
    if not u:
        u = m.User(email=email, name=name, role=role, password_hash="")
        db.add(u)
    u.role = role
    u.password_hash = hash_password(PASSWORD)
    u.must_change_password = False
    db.flush()
    return u


def make_owner(db, club: m.FanClub, u: m.User) -> None:
    """Deixa `u` como dono do fã clube (o dono anterior, se houver, vira ajudante)."""
    staff = db.scalars(select(m.ClubStaff).where(m.ClubStaff.club_id == club.id)).all()
    for st in staff:
        if st.role == m.STAFF_OWNER and st.user_id != u.id:
            st.role = m.STAFF_HELPER
            st.role_label = "Ajudante"
    mine = next((st for st in staff if st.user_id == u.id), None)
    if mine:
        mine.role, mine.role_label = m.STAFF_OWNER, "Dono do fã clube"
    else:
        db.add(m.ClubStaff(club_id=club.id, user_id=u.id, role=m.STAFF_OWNER, role_label="Dono do fã clube"))
    db.flush()


def main() -> None:
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe. Suba a API uma vez para criá-lo.")
        master = db.scalar(select(m.FanClub).where(m.FanClub.artist_id == artist.id, m.FanClub.is_master.is_(True)))
        if not master:
            raise SystemExit("O fã clube master não existe.")

        # Admin do ambiente: aproveita a conta de teste original (vintage@superfas.dev) se for ela que existe.
        old = db.scalar(select(m.User).where(m.User.email == "vintage@superfas.dev"))
        if old and not db.scalar(select(m.User).where(m.User.email == ADMIN[0])):
            old.email = ADMIN[0]
            db.flush()
        admin = user(db, ADMIN[0], ADMIN[1], m.ROLE_ARTIST_ADMIN)
        make_owner(db, master, admin)
        print(f"admin do ambiente: {admin.email}")

        # Donos dos fã clubes (cria o fã clube se ainda não existir).
        for name, city, desc, email, owner_name in OWNERS:
            club = db.scalar(select(m.FanClub).where(m.FanClub.artist_id == artist.id, m.FanClub.name == name))
            if not club:
                club = create_club(db, artist, name, desc, city)
            owner = user(db, email, owner_name, m.ROLE_ARTIST_ADMIN)
            owner.city = owner.city or city
            make_owner(db, club, owner)
            print(f"dono de {name}: {owner.email}")

        # Fã: entra no ambiente e no fã clube master.
        fan = user(db, FAN[0], FAN[1], m.ROLE_FAN)
        if not db.scalar(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == fan.id)):
            db.add(m.Fandom(artist_id=artist.id, user_id=fan.id))
        if not db.scalar(select(m.ClubMember).where(m.ClubMember.club_id == master.id, m.ClubMember.user_id == fan.id)):
            db.add(m.ClubMember(club_id=master.id, user_id=fan.id))
        print(f"fã: {fan.email}")

        db.commit()
    print("Pronto. Senha das contas:", "a definida em CONTAS_SENHA" if os.environ.get("CONTAS_SENHA") else "senha123")


main()
