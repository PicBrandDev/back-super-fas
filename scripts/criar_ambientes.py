"""Cria os ambientes (um por cantor) pela API do admin master. Não duplica: pula quem já existe.

Local:    PYTHONPATH=. .venv/Scripts/python.exe scripts/criar_ambientes.py
Servidor: BASE=https://... MASTER_EMAIL=... MASTER_SENHA=... python scripts/criar_ambientes.py
Os ambientes nascem em "setup" (modo configuração) e em branco; o visual e o status "ativo" se ajustam no admin.
"""

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://localhost:8000")
EMAIL = os.environ.get("MASTER_EMAIL", "admin@superfas.dev")
SENHA = os.environ.get("MASTER_SENHA", "senha123")

ARTISTAS = [
    ("BTS", "bts"),
    ("Taylor Swift", "taylorswift"),
    ("Bad Bunny", "badbunnypr"),
    ("BLACKPINK", "blackpinkofficial"),
    ("Zé Felipe", "zefelipe"),
    ("Ana Castela", "anacastelaoficial"),
    ("Natanzinho Lima", "natanzinholima"),
    ("Anitta e Matuê", "anitta"),
    ("Xand Avião", "xandaviao"),
    ("Departamento", "departamento"),
]


def slug(nome):
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def call(method, path, body=None, token=None):
    # O Cloudflare do servidor bloqueia o User-Agent padrão do Python (erro 1010).
    h = {"User-Agent": "superfas-scripts/1.0"}
    if body is not None:
        h["content-type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


code, r = call("POST", "/auth/login", {"email": EMAIL, "password": SENHA})
if code != 200:
    raise SystemExit(f"login do master falhou ({code}): {r}")
token = r["token"]

for nome, insta in ARTISTAS:
    s = slug(nome)
    if call("GET", f"/artists/{s}", None, token)[0] == 200:
        print(f"{nome}: já existe ({s})")
        continue
    code, r = call("POST", "/admin/fan-clubs", {"name": nome, "instagram": "@" + insta, "template": "blank", "invites": []}, token)
    print(f"{nome}: {code}", r["artist"]["slug"] if code == 201 else r)
