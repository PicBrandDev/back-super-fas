"""Lista quem aceitou o termo de confidencialidade (CPF, ambiente, data, IP) em CSV, do mais novo ao mais antigo.

Local:    PYTHONPATH=. python scripts/listar_aceites.py > aceites.csv
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/listar_aceites.py > ~/aceites.csv

O CPF é dado pessoal (LGPD): guarde o arquivo em lugar restrito e não o envie por canais abertos.
"""

import csv
import sys

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal


def fmt(cpf: str) -> str:
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf


with SessionLocal() as db:
    rows = list(db.scalars(select(m.TermsAcceptance).order_by(m.TermsAcceptance.created_at.desc())))
    out = csv.writer(sys.stdout)
    out.writerow(["data", "cpf", "ambiente", "versao_termo", "ip", "navegador"])
    for a in rows:
        out.writerow([a.created_at.strftime("%Y-%m-%d %H:%M:%S"), fmt(a.cpf), a.artist_slug, a.terms_version, a.ip, a.user_agent])
    print(f"{len(rows)} aceites ({len({a.cpf for a in rows})} CPFs diferentes)", file=sys.stderr)
