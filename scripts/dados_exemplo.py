"""Preenche o fã clube Vintage Culture com dados de exemplo (shows, posts, loja, fãs, campanhas…).

Usa a própria API, então funciona tanto no seu computador quanto no servidor:

    python scripts/dados_exemplo.py                         # API em http://localhost:8001
    python scripts/dados_exemplo.py --api http://localhost:8000 --senha superfas123

Precisa das contas de teste criadas na primeira subida (admin@, vintage@ e marca@superfas.dev)
com a senha de SEED_PASSWORD. Os fãs de exemplo são criados com essa mesma senha.
Se o fã clube já tiver shows, não faz nada (use --forcar para inserir de novo).
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

    if api.must("GET", f"{base}/events", admin) and not a.forcar:
        print("O fã clube já tem shows; nada foi feito. Use --forcar para inserir de novo.")
        return

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
    for name in ("prizes", "products", "tracks", "perks"):
        for i, item in enumerate(DATA[name]):
            api.must("POST", f"{base}/manage/{name}", admin, json_body={**item, "position": i})
    print("✓ Drop News, PicKap, loja, Drops Hits e benefícios")

    # Fãs
    for f in DATA["fans"]:
        status, body = api.call(
            "POST",
            "/auth/register",
            json_body={"name": f["name"], "email": f["email"], "password": a.senha, "handle": f["handle"], "city": f["city"], "artist": slug},
        )
        token = body["token"] if status == 201 else api.login(f["email"], a.senha)
        if f.get("post"):
            api.must("POST", f"{base}/posts", token, json_body={"kind": "galera", "text": f["post"]})
        if f.get("instagram"):
            api.must("POST", f"{base}/posts", token, json_body={"kind": "instagram", "text": "Trouxe esse post do Instagram dele pra galera comentar aqui.", "url": f["instagram"]})
        if f.get("member"):
            api.must("POST", f"{base}/membership/subscribe", token, json_body={"method": f["member"]})
    canceled = {f["handle"] for f in DATA["fans"] if f.get("cancel")}
    for m in api.must("GET", f"{base}/members", admin):
        if m["handle"].lstrip("@") in canceled:
            api.must("POST", f"{base}/members/{m['id']}/cancel", admin)
    print(f"✓ {len(DATA['fans'])} fãs (senha: {a.senha}) com posts e assinaturas")

    # Mídia
    for key, cents in DATA["slotPrices"].items():
        api.must("PATCH", f"{base}/ad-slots/{key}", master, json_body={"priceCents": cents})
    today = date.today()
    for c in DATA["campaigns"]:
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
            api.must("POST", f"/admin/campaigns/{camp['id']}/approve", master)
    print(f"✓ preços das vitrines e {len(DATA['campaigns'])} campanhas do patrocinador")
    print("Pronto!")


if __name__ == "__main__":
    main()
