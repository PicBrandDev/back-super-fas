"""Cria o login de cada patrocinador que ainda não tem e mostra e-mail e senha de todos, para você entrar no portal
(`/patrocinador/login`) e ver as vitrines que cada um comprou.

Os patrocinadores de exemplo (Adidas, Nike, Spotify...) existem só como cadastro, sem usuário: não há senha para recuperar.
Este script cria o usuário (papel "patrocinador") com uma senha aleatória, que aparece uma única vez na tela. A senha fica
guardada só como hash, então ela não dá para consultar depois. Quem já tem login não é mexido, a não ser que você use --redefinir
(aí a senha dele é trocada por uma nova e mostrada).

Servidor:  cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/logins_patrocinadores.py
           (para trocar as senhas dos que já têm login: acrescente  --redefinir  depois do traço)
Local:     PYTHONPATH=. python scripts/logins_patrocinadores.py
"""

import sys

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.security import hash_password, temp_password

redefinir = "--redefinir" in sys.argv

linhas = []
with SessionLocal() as db:
    for sp in db.scalars(select(m.Sponsor).order_by(m.Sponsor.brand)):
        user = sp.users[0] if sp.users else None
        if user is None:
            dono = db.scalar(select(m.User).where(m.User.email == sp.email))
            if dono is not None:  # o e-mail já é de outra conta: não dá para criar
                linhas.append((sp.brand, sp.email, f"(o e-mail já é de outra conta: {dono.role})"))
                continue
            senha = temp_password()
            db.add(m.User(email=sp.email, name=sp.brand or sp.email.split("@")[0], password_hash=hash_password(senha), role=m.ROLE_SPONSOR, sponsor=sp))
            sp.status = "active"
            linhas.append((sp.brand, sp.email, senha))
        elif redefinir:
            senha = temp_password()
            user.password_hash = hash_password(senha)
            user.must_change_password = False
            linhas.append((sp.brand, user.email, senha))
        else:
            linhas.append((sp.brand, user.email, "(já tem login; use --redefinir para gerar uma senha nova)"))
    db.commit()

print("\nPortal do patrocinador: /patrocinador/login\n")
largura = max((len(b) for b, _, _ in linhas), default=8)
for marca, email, senha in linhas:
    print(f"{marca:<{largura}}  {email:<34}  {senha}")
print("\nGuarde as senhas agora: elas não aparecem de novo. Troque-as depois pelo painel do perfil de cada um.")
