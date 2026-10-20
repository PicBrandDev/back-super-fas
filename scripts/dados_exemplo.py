"""Preenche o ambiente Vintage Culture com dados de exemplo: conteúdo oficial, 3 fã clubes
com donos e ajudantes, fãs, posts, roletas e campanhas.

Usa a própria API, então funciona tanto no seu computador quanto no servidor:

    python scripts/dados_exemplo.py                         # API em http://localhost:8001
    python scripts/dados_exemplo.py --api http://localhost:8000 --senha superfas123

Precisa das contas de teste criadas na primeira subida (admin@, vintage@ e marca@superfas.dev)
com a senha de SEED_PASSWORD. Fãs, donos e ajudantes de exemplo ficam com essa mesma senha.
Completa só o que falta: se o ambiente já tem shows, pula o conteúdo oficial; se já tem
outros fã clubes além do master, pula os fã clubes. Use --forcar para inserir tudo de novo.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

DATA = json.loads((Path(__file__).parent / "dados_exemplo.json").read_text(encoding="utf-8"))


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, token: str | None = None, json_body=None, form=None, ok=(200, 201, 204)):
        headers = {}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as res:
                body = res.read()
                return res.status, (json.loads(body) if body else None)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code in ok:
                return e.code, None
            return e.code, body

    def must(self, method, path, token=None, **kw):
        status, body = self.call(method, path, token, **kw)
        if status not in (200, 201, 204):
            sys.exit(f"Falhou {method} {path}: {status} {body}")
        return body

    def login(self, email: str, password: str) -> str:
        return self.must("POST", "/auth/login", json_body={"email": email, "password": password})["token"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8001")
    ap.add_argument("--senha", default=DATA["password"])
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args()

    api = Api(a.api)
    slug = DATA["artist"]
    base = f"/artists/{slug}"
    master = api.login("admin@superfas.dev", a.senha)
    admin = api.login("vintage@superfas.dev", a.senha)
    sponsor = api.login("marca@superfas.dev", a.senha)

    has_content = bool(api.must("GET", f"{base}/events", admin)) and not a.forcar
    has_clubs = len(api.must("GET", f"{base}/clubs", admin)) > 1 and not a.forcar
    if has_content and has_clubs:
        print("O ambiente já tem conteúdo e fã clubes; nada foi feito. Use --forcar para inserir de novo.")
        return
    if has_content:
        print("• conteúdo oficial já existe: só os fã clubes serão criados")
    else:
        official(api, admin, base)
    if not has_clubs:
        clubs(api, admin, base, a.senha)
    fans(api, admin, base, slug, a.senha, only_clubs=has_content)
    media(api, master, sponsor, base, slug, only_clubs=has_content)
    print("Pronto!")


def official(api: Api, admin: str, base: str) -> None:
    # Agenda
    for ev in DATA["events"]:
        payload = {k: v for k, v in ev.items() if k not in ("vendors", "gifts")}
        e = api.must("POST", f"{base}/manage/events", admin, json_body=payload)
        for i, v in enumerate(ev["vendors"]):
            api.must("POST", f"{base}/manage/vendors", admin, json_body={**v, "eventId": e["id"], "position": i})
        for i, g in enumerate(ev["gifts"]):
            api.must("POST", f"{base}/manage/gifts", admin, json_body={**g, "eventId": e["id"], "position": i})
    print(f"✓ {len(DATA['events'])} shows com onde comprar e brindes")

    # Conteúdo
    for p in reversed(DATA["drops"]):  # o primeiro da lista fica como o mais recente
        api.must("POST", f"{base}/manage/posts", admin, json_body={"kind": "drop", **p})
    for name in ("products", "tracks", "perks"):
        for i, item in enumerate(DATA[name]):
            api.must("POST", f"{base}/manage/{name}", admin, json_body={**item, "position": i})
    for i, item in enumerate(DATA["prizes"]):  # roleta do fã clube master
        api.must("POST", f"{base}/clubs/oficial/manage/prizes", admin, json_body={**item, "position": i})
    print("✓ Drop News, loja, Drops Hits, benefícios e PicKap do fã clube master")


def clubs(api: Api, admin: str, base: str, senha: str) -> None:
    # Fã clubes: o admin master do cantor cria e escolhe o dono; o dono convida ajudantes.
    def activate(email: str, temp: str | None) -> str:
        """Entra com a senha provisória e troca para a senha padrão do exemplo."""
        if not temp:
            return api.login(email, senha)
        t = api.login(email, temp)
        return api.must("POST", "/auth/change-password", t, json_body={"currentPassword": temp, "newPassword": senha})["token"]

    for c in DATA["clubs"]:
        r = api.must(
            "POST",
            f"{base}/clubs",
            admin,
            json_body={"name": c["name"], "city": c["city"], "description": c["description"],
                       "ownerEmail": c["owner"]["email"], "ownerName": c["owner"]["name"]},
        )
        club = r["club"]["slug"]
        owner = activate(c["owner"]["email"], r["invite"]["tempPassword"])
        for h in c["helpers"]:
            inv = api.must("POST", f"{base}/clubs/{club}/staff", owner,
                           json_body={"email": h["email"], "name": h["name"], "role": "helper", "roleLabel": h["label"]})
            activate(h["email"], inv["tempPassword"])
        for i, item in enumerate(c["prizes"]):
            api.must("POST", f"{base}/clubs/{club}/manage/prizes", owner, json_body={**item, "position": i})
    print(f"✓ {len(DATA['clubs'])} fã clubes com donos, ajudantes e roletas (senha: a mesma das contas de teste)")


def fans(api: Api, admin: str, base: str, slug: str, senha: str, only_clubs: bool) -> None:
    for f in DATA["fans"]:
        status, body = api.call(
            "POST",
            "/auth/register",
            json_body={"name": f["name"], "email": f["email"], "password": senha, "handle": f["handle"], "city": f["city"], "artist": slug},
        )
        token = body["token"] if status == 201 else api.login(f["email"], senha)
        for club in f.get("clubs", []):
            api.must("POST", f"{base}/clubs/{club}/join", token)
        if only_clubs:
            continue  # posts e assinaturas já foram criados antes
        target = (f.get("clubs") or ["oficial"])[0]
        if f.get("post"):
            api.must("POST", f"{base}/clubs/{target}/posts", token, json_body={"kind": "galera", "text": f["post"]})
        if f.get("instagram"):
            api.must("POST", f"{base}/clubs/{target}/posts", token, json_body={"kind": "instagram", "text": "Trouxe esse post do Instagram dele pra galera comentar aqui.", "url": f["instagram"]})
        if f.get("member"):
            api.must("POST", f"{base}/membership/subscribe", token, json_body={"method": f["member"]})
    if only_clubs:
        print(f"✓ {len(DATA['fans'])} fãs entraram nos fã clubes")
        return
    canceled = {f["handle"] for f in DATA["fans"] if f.get("cancel")}
    for m in api.must("GET", f"{base}/members", admin):
        if m["handle"].lstrip("@") in canceled:
            api.must("POST", f"{base}/members/{m['id']}/cancel", admin)
    print(f"✓ {len(DATA['fans'])} fãs (senha: a mesma das contas de teste) nos fã clubes, com posts e assinaturas")


def media(api: Api, master: str, sponsor: str, base: str, slug: str, only_clubs: bool) -> None:
    if not only_clubs:
        for key, cents in DATA["slotPrices"].items():
            api.must("PATCH", f"{base}/ad-slots/{key}", master, json_body={"priceCents": cents})
    today = date.today()
    campaigns = [c for c in DATA["campaigns"] if not only_clubs or "." in c["slot"]]
    for c in campaigns:
        form = {
            "club": slug,
            "slot": c["slot"],
            "brand": c["brand"],
            "title": c["title"],
            "text": c["text"],
            "cta": c["cta"],
            "link": c["link"],
            "start": (today + timedelta(days=c["startOffset"])).isoformat(),
            "end": (today + timedelta(days=c["endOffset"])).isoformat(),
        }
        camp = api.must("POST", "/sponsor/campaigns", sponsor, form=form)
        if c.get("approve"):
            api.must("POST", f"/campaigns/{camp['id']}/approve", master)
    print(f"✓ {len(campaigns)} campanhas do patrocinador")


if __name__ == "__main__":
    main()
