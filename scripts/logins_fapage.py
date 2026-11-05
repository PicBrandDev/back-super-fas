"""Deixa o login de todo patrocinador como <marca>@fapage.com.br com a senha 123 (só para demonstração).

Cria o usuário (papel "patrocinador") se o patrocinador ainda não tiver, ou troca e-mail e senha do que já existe.

Servidor:  cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/logins_fapage.py
Local:     PYTHONPATH=. python scripts/logins_fapage.py
"""

import re
import unicodedata

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.security import hash_password

SENHA = "123"
DOMINIO = "fapage.com.br"


def slug(marca: str) -> str:
    s = unicodedata.normalize("NFKD", marca).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


linhas = []
with SessionLocal() as db:
    for sp in db.scalars(select(m.Sponsor).order_by(m.Sponsor.brand)):
        email = f"{slug(sp.brand or sp.email.split('@')[0])}@{DOMINIO}"
        user = sp.users[0] if sp.users else None
        outro = db.scalar(select(m.User).where(m.User.email == email))
        if outro is not None and outro is not user:
            linhas.append((sp.brand, email, f"(e-mail já é de outra conta: {outro.role})"))
            continue
        if user is None:
            user = m.User(email=email, name=sp.brand or email.split("@")[0], password_hash=hash_password(SENHA), role=m.ROLE_SPONSOR, sponsor=sp)
            db.add(user)
        else:
            user.email = email
            user.password_hash = hash_password(SENHA)
        user.must_change_password = False
        sp.email = email
        sp.status = "active"
        linhas.append((sp.brand, email, SENHA))
    db.commit()

print("\nPortal do patrocinador: /patrocinador/login\n")
largura = max((len(b) for b, _, _ in linhas), default=8)
for marca, email, senha in linhas:
    print(f"{marca:<{largura}}  {email:<32}  {senha}")
