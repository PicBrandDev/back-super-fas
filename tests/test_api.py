from datetime import date, timedelta

from conftest import login

VC = "/artists/vintage-culture"


# ---------------------------------------------------------------- login e permissões


def test_login_por_papel(client):
    for email, role in [
        ("admin@superfas.dev", "master"),
        ("vintage@superfas.dev", "artist_admin"),
        ("marca@superfas.dev", "sponsor"),
        ("fa@superfas.dev", "fan"),
    ]:
        r = client.post("/auth/login", json={"email": email, "password": "senha-de-teste"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == role
    admin = client.post("/auth/login", json={"email": "vintage@superfas.dev", "password": "senha-de-teste"}).json()
    assert admin["user"]["artists"] == ["vintage-culture"]


def test_login_errado(client):
    r = client.post("/auth/login", json={"email": "admin@superfas.dev", "password": "errada"})
    assert r.status_code == 401


def test_conteudo_exige_login(client):
    assert client.get(f"{VC}/events").status_code == 401
    assert client.get("/artists").status_code == 200  # lista pública (tela de cadastro)


def test_cadastro_de_fa(client):
    r = client.post(
        "/auth/register",
        json={"name": "Nova Fã", "email": "nova@exemplo.com", "password": "12345678", "handle": "nova", "artist": "vintage-culture"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "fan"
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    me = client.get("/me?artist=vintage-culture", headers=h).json()
    assert me["handle"] == "@nova" and me["spins"] == 3 and me["isMember"] is False
    # e-mail repetido
    again = client.post("/auth/register", json={"name": "Outra", "email": "nova@exemplo.com", "password": "12345678"})
    assert again.status_code == 409


def test_permissoes(client, fan, club_admin, sponsor):
    assert client.get("/admin/campaigns", headers=fan).status_code == 403
    assert client.get("/admin/campaigns", headers=club_admin).status_code == 403
    assert client.post(f"{VC}/manage/events", headers=fan, json={"date": "2026-12-01", "city": "X"}).status_code == 403
    assert client.get(f"{VC}/members", headers=sponsor).status_code == 403
    assert client.post("/admin/fan-clubs", headers=club_admin, json={"name": "Outro"}).status_code == 403
    assert client.get("/sponsor/campaigns", headers=fan).status_code == 403


# ---------------------------------------------------------------- conteúdo pelo admin do fã clube


def test_admin_cria_conteudo_e_fa_ve(client, club_admin, fan):
    ev = client.post(
        f"{VC}/manage/events",
        headers=club_admin,
        json={"date": "2026-11-07", "city": "São Paulo", "venue": "Arena", "time": "23h", "status": "on_sale"},
    )
    assert ev.status_code == 201, ev.text
    eid = ev.json()["id"]
    assert client.post(f"{VC}/manage/vendors", headers=club_admin, json={"eventId": eid, "name": "Ticketeira", "tag": "Oficial", "priceLabel": "a partir de R$ 120"}).status_code == 201
    assert client.post(f"{VC}/manage/gifts", headers=club_admin, json={"eventId": eid, "name": "Pôster", "phase": "before", "qtyLabel": "10 un."}).status_code == 201
    assert client.post(f"{VC}/manage/posts", headers=club_admin, json={"text": "Bastidores da turnê", "hasImage": True}).status_code == 201
    assert client.post(f"{VC}/manage/products", headers=club_admin, json={"name": "Camiseta", "priceCents": 8990}).status_code == 201
    assert client.post(f"{VC}/manage/tracks", headers=club_admin, json={"title": "Faixa 01", "meta": "Prévia nova"}).status_code == 201
    assert client.post(f"{VC}/manage/perks", headers=club_admin, json={"title": "Drop News exclusivos", "sub": "Só membros"}).status_code == 201
    for label, retry, pts in [("Camiseta", False, 0), ("+50 pts", False, 50), ("Tente de novo", True, 0)]:
        assert client.post(f"{VC}/manage/prizes", headers=club_admin, json={"label": label, "isRetry": retry, "points": pts}).status_code == 201

    events = client.get(f"{VC}/events", headers=fan).json()
    sp = next(e for e in events if e["id"] == eid)
    assert (sp["weekday"], sp["day"], sp["month"], sp["monthKey"]) == ("SÁB", "07", "NOV", "nov")
    assert sp["giftsCount"] == 1
    assert client.get(f"{VC}/events/{eid}/vendors", headers=fan).json()[0]["priceLabel"] == "a partir de R$ 120"
    assert client.get(f"{VC}/events/{eid}/gifts", headers=fan).json()[0]["qtyLabel"] == "10 un."
    drop = client.get(f"{VC}/posts?kind=drop", headers=fan).json()[0]
    assert drop["author"]["official"] is True and drop["author"]["name"] == "Vintage Culture"
    assert client.get(f"{VC}/products", headers=fan).json()[0]["priceLabel"] == "R$ 89,90"
    assert client.get(f"{VC}/tracks", headers=fan).json()[0]["num"] == "01"
    assert len(client.get(f"{VC}/pickap/prizes", headers=fan).json()) == 3
    assert client.get(f"{VC}/membership/perks", headers=fan).json()[0]["title"] == "Drop News exclusivos"

    # editar e apagar
    pid = client.get(f"{VC}/manage/products", headers=club_admin).json()[0]["id"]
    r = client.patch(f"{VC}/manage/products/{pid}", headers=club_admin, json={"priceCents": 9990})
    assert r.json()["priceCents"] == 9990
    assert client.delete(f"{VC}/manage/products/{pid}", headers=club_admin).status_code == 204
    assert client.get(f"{VC}/products", headers=fan).json() == []


def test_acoes_do_fa(client, fan, club_admin):
    r = client.post(f"{VC}/posts", headers=fan, json={"kind": "galera", "text": "Bora caravana!"})
    assert r.status_code == 201 and r.json()["author"]["handle"] == "@fa.teste"

    before = client.get("/me?artist=vintage-culture", headers=fan).json()
    spin = client.post(f"{VC}/pickap/spin", headers=fan)
    assert spin.status_code == 200, spin.text
    assert spin.json()["spinsLeft"] in (before["spins"] - 1, before["spins"])

    ev = client.get(f"{VC}/events", headers=fan).json()[0]
    assert client.post(f"{VC}/events/{ev['id']}/luck/join", headers=fan).json() == {"joined": True}

    sub = client.post(f"{VC}/membership/subscribe", headers=fan, json={"method": "pix"})
    assert sub.json()["isMember"] is True
    members = client.get(f"{VC}/members", headers=club_admin).json()
    me = next(m for m in members if m["handle"] == "@fa.teste")
    assert me["status"] == "active" and me["payment"] == "Pix"
    assert client.post(f"{VC}/members/{me['id']}/cancel", headers=club_admin).status_code == 200
    assert client.get("/me?artist=vintage-culture", headers=fan).json()["isMember"] is False


def test_evento_de_outro_fa_clube_e_recusado(client, master, club_admin):
    created = client.post("/admin/fan-clubs", headers=master, json={"name": "Artista X"}).json()
    slug = created["artist"]["slug"]
    other = client.post(f"/artists/{slug}/manage/events", headers=master, json={"date": "2026-12-01", "city": "Rio"}).json()
    r = client.post(f"{VC}/manage/vendors", headers=club_admin, json={"eventId": other["id"], "name": "Hack"})
    assert r.status_code == 400
    # e o admin do VC não mexe no outro fã clube
    assert client.get(f"/artists/{slug}/manage/events", headers=club_admin).status_code == 403


# ---------------------------------------------------------------- admin master


def test_master_cria_fa_clube_com_convites(client, master, fan):
    r = client.post(
        "/admin/fan-clubs",
        headers=master,
        json={"name": "Alok", "instagram": "@alok", "template": "vc", "invites": ["equipe@alok.com"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["artist"]["slug"] == "alok" and body["artist"]["status"] == "setup"
    assert body["artist"]["adSlotsSummary"] == "0 de 6 ocupadas"
    invite = body["invites"][0]
    assert invite["tempPassword"]

    # em configuração: fã não vê; o admin convidado vê
    assert client.get("/artists/alok", headers=fan).status_code == 404
    h = login(client, "equipe@alok.com", invite["tempPassword"])
    assert client.get("/auth/me", headers=h).json()["mustChangePassword"] is True
    assert client.get("/artists/alok", headers=h).status_code == 200
    # a estrutura do VC (roleta e benefícios) foi copiada
    assert len(client.get("/artists/alok/manage/prizes", headers=h).json()) == 3

    # troca de senha
    r = client.post("/auth/change-password", headers=h, json={"currentPassword": invite["tempPassword"], "newPassword": "novasenha123"})
    assert r.status_code == 200 and r.json()["user"]["mustChangePassword"] is False
    login(client, "equipe@alok.com", "novasenha123")

    # equipe
    admins = client.get("/artists/alok/admins", headers=master).json()
    assert admins[0]["email"] == "equipe@alok.com"
    assert client.post("/artists/alok/admins", headers=master, json={"email": "fa@superfas.dev"}).status_code == 409

    # ativar
    r = client.patch("/admin/fan-clubs/alok", headers=master, json={"status": "active", "modules": {"loja": False}})
    assert r.json()["status"] == "active" and r.json()["modules"]["loja"] is False
    assert client.get("/artists/alok", headers=fan).status_code == 200


# ---------------------------------------------------------------- mídia


def test_campanha_do_patrocinador_ate_ir_ao_ar(client, master, sponsor, fan):
    today = date.today()
    form = {
        "club": "vintage-culture",
        "slot": "home",
        "brand": "Marca Teste",
        "title": "Promo de verão",
        "text": "Desconto para o fã clube",
        "cta": "Ver",
        "link": "https://exemplo.com",
        "start": (today - timedelta(days=1)).isoformat(),
        "end": (today + timedelta(days=6)).isoformat(),
    }
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    r = client.post("/sponsor/campaigns", headers=sponsor, data=form, files={"art": ("arte.png", png, "image/png")})
    assert r.status_code == 201, r.text
    camp = r.json()
    assert camp["status"] == "pending" and camp["artUrl"].startswith("/uploads/")
    assert client.get(camp["artUrl"]).status_code == 200
    assert client.get(f"{VC}/ads/home", headers=fan).json() is None

    assert client.post(f"/admin/campaigns/{camp['id']}/approve", headers=master).json()["status"] == "live"
    ad = client.get(f"{VC}/ads/home", headers=fan).json()
    assert ad["title"] == "Promo de verão" and ad["sponsor"] == "Marca Teste"
    slots = client.get(f"{VC}/ad-slots", headers=sponsor).json()
    assert next(s for s in slots if s["id"] == "home")["occupied"] is True
    assert client.get("/sponsor/campaigns", headers=sponsor).json()[0]["id"] == camp["id"]

    # vitrine desligada não aceita campanha
    client.patch(f"{VC}/ad-slots/loja", headers=master, json={"active": False, "priceCents": 50000})
    form["slot"] = "loja"
    assert client.post("/sponsor/campaigns", headers=sponsor, data=form).status_code == 400


def test_convite_de_patrocinador(client, master):
    r = client.post("/admin/sponsors/invite", headers=master, json={"email": "contato@marca-b.com", "brand": "Marca B"})
    assert r.status_code == 201
    pw = r.json()["tempPassword"]
    assert r.json()["sponsor"]["status"] == "invited"
    login(client, "contato@marca-b.com", pw)
    sp = next(s for s in client.get("/admin/sponsors", headers=master).json() if s["email"] == "contato@marca-b.com")
    assert sp["status"] == "active"
