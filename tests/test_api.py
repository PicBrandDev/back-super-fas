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
    assert admin["user"]["clubs"] == ["vintage-culture/oficial"]


def test_login_errado(client):
    r = client.post("/auth/login", json={"email": "admin@superfas.dev", "password": "errada"})
    assert r.status_code == 401


def test_conteudo_exige_login(client):
    assert client.get(f"{VC}/events").status_code == 401
    assert client.get("/artists").status_code == 200  # lista pública (tela de cadastro)


def test_cadastro_de_fa(client):
    r = client.post(
        "/auth/register",
        json={
            "name": "Nova Fã", "email": "nova@exemplo.com", "password": "12345678", "handle": "nova", "artist": "vintage-culture",
            "zipCode": "01310-100", "street": "Av. Paulista", "number": "1000", "neighborhood": "Bela Vista",
            "city": "São Paulo", "state": "sp",
        },
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
        r = client.post(f"{VC}/clubs/oficial/manage/prizes", headers=club_admin, json={"label": label, "isRetry": retry, "points": pts})
        assert r.status_code == 201, r.text

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
    assert len(client.get(f"{VC}/pickup/prizes", headers=fan).json()) == 3
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
    spin = client.post(f"{VC}/pickup/spin", headers=fan)
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
    assert body["artist"]["adSlotsSummary"] == "0 de 12 ocupadas"
    invite = body["invites"][0]
    assert invite["tempPassword"]

    # em configuração: fã não vê; o admin convidado vê
    assert client.get("/artists/alok", headers=fan).status_code == 404
    h = login(client, "equipe@alok.com", invite["tempPassword"])
    assert client.get("/auth/me", headers=h).json()["mustChangePassword"] is True
    assert client.get("/artists/alok", headers=h).status_code == 200
    # a estrutura do VC (roleta e benefícios) foi copiada
    assert len(client.get("/artists/alok/clubs/oficial/manage/prizes", headers=h).json()) == 3
    assert client.get("/auth/me", headers=h).json()["artists"] == ["alok"]

    # troca de senha
    r = client.post("/auth/change-password", headers=h, json={"currentPassword": invite["tempPassword"], "newPassword": "novasenha123"})
    assert r.status_code == 200 and r.json()["user"]["mustChangePassword"] is False
    login(client, "equipe@alok.com", "novasenha123")

    # equipe
    staff = client.get("/artists/alok/clubs/oficial/staff", headers=master).json()
    assert staff[0]["email"] == "equipe@alok.com" and staff[0]["role"] == "owner"
    assert client.post("/artists/alok/clubs/oficial/staff", headers=master, json={"email": "fa@superfas.dev"}).status_code == 409

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


# ---------------------------------------------------------------- fã clubes do cantor


def test_fa_clubes_do_ambiente(client, club_admin, fan, sponsor, master):
    # O admin master do cantor (dono do clube master) cria um fã clube e escolhe o dono.
    r = client.post(
        f"{VC}/clubs",
        headers=club_admin,
        json={"name": "Fã Clube SP", "city": "São Paulo", "ownerEmail": "dono-sp@exemplo.com", "ownerName": "Dono SP"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["club"]["slug"] == "fa-clube-sp"
    owner = login(client, "dono-sp@exemplo.com", r.json()["invite"]["tempPassword"])
    me = client.get("/auth/me", headers=owner).json()
    assert me["artists"] == [] and me["clubs"] == ["vintage-culture/fa-clube-sp"]
    SP = f"{VC}/clubs/fa-clube-sp"

    # O dono do clube não mexe no conteúdo oficial nem em outro clube, e não escolhe dono.
    assert client.post(f"{VC}/manage/events", headers=owner, json={"date": "2026-12-01", "city": "X"}).status_code == 403
    assert client.get(f"{VC}/clubs/oficial/staff", headers=owner).status_code == 403
    assert client.post(f"{SP}/staff", headers=owner, json={"email": "x@exemplo.com", "role": "owner"}).status_code == 403
    assert client.post(f"{VC}/clubs", headers=owner, json={"name": "Outro"}).status_code == 403

    # Mas convida ajudantes; o ajudante não convida ninguém.
    inv = client.post(f"{SP}/staff", headers=owner, json={"email": "ajuda-sp@exemplo.com", "role": "helper"})
    assert inv.status_code == 201, inv.text
    helper = login(client, "ajuda-sp@exemplo.com", inv.json()["tempPassword"])
    assert client.post(f"{SP}/staff", headers=helper, json={"email": "y@exemplo.com"}).status_code == 403
    assert {s["role"] for s in client.get(f"{SP}/staff", headers=owner).json()} == {"owner", "helper"}

    # PicKup do clube
    assert client.post(f"{SP}/manage/prizes", headers=helper, json={"label": "Boné SP"}).status_code == 201

    # Fã: lista, entra, posta e gira
    clubs = client.get(f"{VC}/clubs", headers=fan).json()
    assert [c["slug"] for c in clubs][:2] == ["oficial", "fa-clube-sp"]
    assert clubs[0]["isMaster"] is True and clubs[1]["owner"]["name"] == "Dono SP"
    assert client.post(f"{SP}/posts", headers=fan, json={"text": "Oi SP"}).status_code == 403  # ainda não entrou
    assert client.post(f"{SP}/join", headers=fan).json()["joined"] is True
    assert "fa-clube-sp" in client.get("/me?artist=vintage-culture", headers=fan).json()["clubs"]
    p = client.post(f"{SP}/posts", headers=fan, json={"text": "Oi SP"})
    assert p.status_code == 201 and p.json()["club"]["slug"] == "fa-clube-sp"
    assert any(x["club"] and x["club"]["slug"] == "fa-clube-sp" for x in client.get(f"{VC}/posts?kind=galera", headers=fan).json())
    spin = client.post(f"{SP}/pickup/spin", headers=fan)
    assert spin.status_code == 200 and spin.json()["prize"]["label"] == "Boné SP"
    assert client.get(f"{SP}/members", headers=owner).json()[0]["handle"] == "@fa.teste"
    assert client.get(f"{SP}/members", headers=fan).status_code == 403

    # Anúncio na vitrine do clube: quem aprova é o dono do clube (outro dono não pode)
    other = client.post(f"{VC}/clubs", headers=club_admin, json={"name": "Fã Clube Rio", "ownerEmail": "dono-rio@exemplo.com"}).json()
    assert other["invite"]["emailSent"] is False  # sem SMTP nos testes: a senha provisória é mostrada na tela
    rio = login(client, "dono-rio@exemplo.com", other["invite"]["tempPassword"])
    slots = client.get(f"{SP}/ad-slots", headers=sponsor).json()
    assert [s["id"] for s in slots] == ["fa-clube-sp.home", "fa-clube-sp.mural", "fa-clube-sp.pickup", "fa-clube-sp.feed_2", "fa-clube-sp.feed_3"]
    today = date.today()
    camp = client.post(
        "/sponsor/campaigns",
        headers=sponsor,
        data={"club": "vintage-culture", "slot": "fa-clube-sp.home", "title": "Promo SP", "link": "https://x.com",
              "start": (today - timedelta(days=1)).isoformat(), "end": (today + timedelta(days=5)).isoformat()},
    ).json()
    assert camp["fanClubSlug"] == "fa-clube-sp"
    assert client.get(f"{SP}/campaigns", headers=owner).json()[0]["id"] == camp["id"]
    assert client.post(f"/campaigns/{camp['id']}/approve", headers=rio).status_code == 403
    assert client.post(f"/campaigns/{camp['id']}/approve", headers=owner).json()["status"] == "live"
    assert client.get(f"{SP}/ads/home", headers=fan).json()["title"] == "Promo SP"
    # e a vitrine do clube não aparece na lista do ambiente
    assert all("." not in s["id"] for s in client.get(f"{VC}/ad-slots", headers=sponsor).json())

    # Sair do clube; não há limite de fã clubes por cantor
    assert client.post(f"{SP}/leave", headers=fan).json()["joined"] is False
    for i in range(12):
        assert client.post(f"{VC}/clubs", headers=club_admin, json={"name": f"Clube {i}"}).status_code == 201
    assert client.delete(f"{VC}/clubs/oficial", headers=master).status_code == 400
    assert client.delete(f"{VC}/clubs/clube-0", headers=club_admin).status_code == 204


# ---------------------------------------------------------------- painel e analytics dos fã clubes


def test_painel_dos_fa_clubes(client, club_admin, fan):
    r = client.get("/artists/vintage-culture/clubs-overview", headers=club_admin)
    assert r.status_code == 200
    master = r.json()[0]
    assert master["isMaster"] and master["ownerName"] and master["members"] >= 1
    assert client.get("/artists/vintage-culture/clubs-overview", headers=fan).status_code == 403

    a = client.get("/artists/vintage-culture/clubs/oficial/analytics", headers=club_admin)
    assert a.status_code == 200
    body = a.json()
    assert len(body["series"]) == 30
    assert body["club"]["slug"] == "oficial"
    assert client.get("/artists/vintage-culture/clubs/oficial/analytics", headers=fan).status_code == 403


def test_analytics_de_assinantes(client, club_admin, fan):
    r = client.get("/artists/vintage-culture/subscribers-analytics", headers=club_admin)
    assert r.status_code == 200
    body = r.json()
    assert body["fans"] >= 2 and len(body["series"]) == 30
    assert body["active"] + body["pending"] + body["canceled"] <= body["fans"]
    assert client.get("/artists/vintage-culture/subscribers-analytics", headers=fan).status_code == 403


def test_drop_news_feed_e_visualizacoes(client, club_admin, fan):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = client.post(
        "/artists/vintage-culture/manage/drops",
        headers=club_admin,
        data={"text": "Novo drop saindo!"},
        files={"image": ("capa.png", png, "image/png")},
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["kind"] == "drop" and item["image"].startswith("/uploads/") and item["views"] == 0
    bad = client.post(
        "/artists/vintage-culture/manage/drops", headers=club_admin, data={"text": "x"}, files={"image": ("a.gif", b"G", "image/gif")}
    )
    assert bad.status_code == 400
    assert client.post("/artists/vintage-culture/manage/drops", headers=fan, data={"text": "x"}).status_code == 403

    assert client.post(f"/artists/vintage-culture/posts/{item['id']}/view", headers=fan).json()["views"] == 1
    feed = client.get("/artists/vintage-culture/manage/feed?kind=drop", headers=club_admin).json()
    assert feed[0]["id"] == item["id"] and feed[0]["views"] == 1
    fan_feed = client.get("/artists/vintage-culture/posts?kind=drop", headers=fan).json()
    assert fan_feed[0]["image"]["src"] == item["image"]


def test_foto_de_perfil_do_fa_clube(client, club_admin, fan):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    url = "/artists/vintage-culture/clubs/oficial/avatar"
    r = client.post(url, headers=club_admin, files={"image": ("perfil.png", png, "image/png")})
    assert r.status_code == 200 and r.json()["avatar"].startswith("/uploads/")
    assert client.post(url, headers=fan, files={"image": ("perfil.png", png, "image/png")}).status_code == 403
    assert client.post(url, headers=club_admin, files={"image": ("x.gif", b"G", "image/gif")}).status_code == 400
    overview = client.get("/artists/vintage-culture/clubs-overview", headers=club_admin).json()
    assert overview[0]["avatar"] == r.json()["avatar"]


def test_feed_do_fa_clube(client, club_admin, fan):
    url = "/artists/vintage-culture/clubs/oficial/feed"
    r = client.get(url, headers=club_admin)
    assert r.status_code == 200
    items = r.json()
    assert items and {"likes", "comments", "views", "image"} <= set(items[0])
    assert client.get(url, headers=fan).status_code == 403


def test_feed_traz_comentarios(client, club_admin, db_session=None):
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal

    with SessionLocal() as db:
        post = db.scalar(select(m.Post).where(m.Post.kind == "drop"))
        fan_user = db.scalar(select(m.User).where(m.User.email == "fa@superfas.dev"))
        db.add(m.PostComment(post_id=post.id, author_id=fan_user.id, text="Que drop!"))
        db.commit()
        post_id = post.id
    feed = client.get("/artists/vintage-culture/manage/feed?kind=drop", headers=club_admin).json()
    item = next(i for i in feed if i["id"] == post_id)
    assert item["comments"] >= 1 and item["recentComments"][-1]["text"] == "Que drop!"


def test_agencias_pacotes_e_ticketeira(client, club_admin, fan):
    base = "/artists/vintage-culture"
    ev = client.post(
        f"{base}/manage/events",
        headers=club_admin,
        json={"date": "2030-05-10", "city": "Curitiba", "ticketingName": "Ticketeira Teste", "ticketingUrl": "https://ticketeira.exemplo.com/show"},
    )
    assert ev.status_code == 201, ev.text
    event = ev.json()
    assert event["ticketingUrl"] == "https://ticketeira.exemplo.com/show"

    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Caravana Sul", "contact": "(41) 99999-0000"}).json()
    pkg = client.post(
        f"{base}/manage/packages",
        headers=club_admin,
        json={
            "eventId": event["id"], "agencyId": ag["id"], "name": "Caravana Curitiba", "transferDetails": "Saída 14h, volta após o show",
            "addons": [
                {"key": "transfer", "priceCents": 9000},
                {"key": "jantar", "priceCents": 45000},
                {"key": "hotel", "priceCents": 38000, "soldOut": True},
            ],
        },
    )
    assert pkg.status_code == 201, pkg.text
    bad = client.post(f"{base}/manage/packages", headers=club_admin, json={"eventId": event["id"], "agencyId": "nao-existe", "name": "x"})
    assert bad.status_code == 400
    # cada show tem uma única agência
    outra = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Outra Agência"}).json()
    dois = client.post(f"{base}/manage/packages", headers=club_admin, json={"eventId": event["id"], "agencyId": outra["id"], "name": "y"})
    assert dois.status_code == 400 and "Caravana Sul" in dois.json()["detail"]
    mesma = client.post(f"{base}/manage/packages", headers=club_admin, json={"eventId": event["id"], "agencyId": ag["id"], "name": "Segundo pacote"})
    assert mesma.status_code == 201
    client.delete(f"{base}/manage/packages/{mesma.json()['id']}", headers=club_admin)
    assert client.post(f"{base}/manage/agencies", headers=fan, json={"name": "x"}).status_code == 403

    pk = client.get(f"{base}/events/{event['id']}/packages", headers=fan).json()
    assert len(pk) == 1 and pk[0]["agencyName"] == "Caravana Sul" and pk[0]["hasTransfer"] is True
    assert pk[0]["fromPriceCents"] == 9000 and pk[0]["items"] == [] and [a["key"] for a in pk[0]["addons"]] == ["transfer", "jantar", "hotel"]
    assert client.get(f"{base}/events/{event['id']}", headers=fan).json()["ticketingName"] == "Ticketeira Teste"


def test_ingressos_avulsos_do_show(client, club_admin, fan):
    base = "/artists/vintage-culture"
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2030-06-01", "city": "Recife"}).json()
    for i, (label, cents) in enumerate([("Pista", 15000), ("Camarote", 30000)]):
        r = client.post(f"{base}/manage/tickets", headers=club_admin, json={"eventId": ev["id"], "label": label, "priceCents": cents, "position": i})
        assert r.status_code == 201, r.text
    assert client.post(f"{base}/manage/tickets", headers=fan, json={"eventId": ev["id"], "label": "x"}).status_code == 403
    out = client.get(f"{base}/events/{ev['id']}/tickets", headers=fan).json()
    assert [t["label"] for t in out] == ["Pista", "Camarote"] and out[0]["priceCents"] == 15000


def test_giros_com_motivo_e_compra_de_experiencias(client, club_admin, fan):
    base = "/artists/vintage-culture"
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2031-01-10", "city": "Natal"}).json()
    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Agência Natal"}).json()
    pkg = client.post(
        f"{base}/manage/packages",
        headers=club_admin,
        json={"eventId": ev["id"], "agencyId": ag["id"], "name": "Caravana Natal", "addons": [
            {"key": "transfer", "priceCents": 9000},
            {"key": "after", "priceCents": 50000, "soldOut": True},
        ]},
    ).json()

    antes = client.get(f"{base}/pickup/spins", headers=fan).json()
    livres_antes = sum(1 for g in antes if not g["used"])
    url = f"{base}/events/{ev['id']}/purchases"
    assert client.post(url, headers=fan, json={"packageId": pkg["id"], "addons": ["after"], "ticketOptin": True}).status_code == 400  # esgotada
    assert client.post(url, headers=fan, json={"packageId": pkg["id"], "addons": [], "ticketOptin": True}).status_code == 400  # sem ingresso: precisa de uma experiência
    compra = client.post(url, headers=fan, json={"packageId": pkg["id"], "addons": ["transfer"], "ticketOptin": True})
    assert compra.status_code == 201, compra.text
    c = compra.json()
    assert c["includesPhotoFinder"] and c["includesTransfer"] and not c["includesSeal"] and c["event"]["city"] == "Natal"
    assert c["label"] == "Transfer ida e volta" and c["priceCents"] == 9000
    assert c["kind"] == "experience"

    meus = client.get(f"{base}/me/tickets", headers=fan).json()
    assert any(t["id"] == c["id"] for t in meus)
    depois = client.get(f"{base}/pickup/spins", headers=fan).json()
    novo = next(g for g in depois if "Compra de experiências extras" in g["reason"] and "Natal" in g["reason"])
    assert sum(1 for g in depois if not g["used"]) == livres_antes + 1

    r = client.post(f"{base}/clubs/oficial/pickup/spin", headers=fan, json={"creditId": novo["id"]})
    assert r.status_code == 200, r.text
    usado = next(g for g in r.json()["credits"] if g["id"] == novo["id"])
    assert usado["used"] and usado["prizeLabel"]
    assert client.post(f"{base}/clubs/oficial/pickup/spin", headers=fan, json={"creditId": novo["id"]}).status_code == 400


def test_photo_finder_com_rekognition_simulado(client, club_admin, fan, monkeypatch):
    from app import rekognition

    indexed: dict[str, list[str]] = {}
    monkeypatch.setattr(rekognition, "enabled", lambda: True)
    monkeypatch.setattr(rekognition, "shared_enabled", lambda: False)  # o .env local pode ter coleção e bucket
    monkeypatch.setattr(rekognition, "index_photo", lambda ev, pid, data: indexed.setdefault(pid, [f"face-{pid}"]))
    monkeypatch.setattr(rekognition, "delete_faces", lambda ev, ids: None)
    monkeypatch.setattr(rekognition, "search_selfie", lambda ev, data: list(indexed)[:1])

    base = "/artists/vintage-culture"
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2020-01-05", "city": "Passado"}).json()
    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Agência Passado"}).json()
    pkg = client.post(
        f"{base}/manage/packages", headers=club_admin,
        json={"eventId": ev["id"], "agencyId": ag["id"], "name": "Caravana", "addons": [{"key": "camarim", "priceCents": 29000}]},
    ).json()

    up = client.post(
        f"{base}/manage/events/{ev['id']}/photos", headers=club_admin,
        files=[("photos", ("a.png", png, "image/png")), ("photos", ("b.png", png, "image/png"))],
    )
    assert up.status_code == 201 and len(up.json()) == 2 and all(p["indexed"] for p in up.json())
    assert client.post(f"{base}/manage/events/{ev['id']}/photos", headers=fan, files=[("photos", ("a.png", png, "image/png"))]).status_code == 403

    selfie = {"selfie": ("eu.png", png, "image/png")}
    # sem ingresso do show, o fã não busca
    st = client.get(f"{base}/events/{ev['id']}/photo-finder", headers=fan).json()
    assert not st["eligible"] and "precisa de um ingresso" in st["reason"]
    assert client.post(f"{base}/events/{ev['id']}/photo-finder/search", headers=fan, files=selfie, data={"consent": "true"}).status_code == 403

    # compra a experiência (o Photo Finder vem em todos os pacotes) e busca
    assert client.post(f"{base}/events/{ev['id']}/purchases", headers=fan, json={"packageId": pkg["id"], "addons": ["camarim"], "ticketOptin": True}).status_code == 201
    assert client.get(f"{base}/events/{ev['id']}/photo-finder", headers=fan).json()["eligible"] is True
    assert client.post(f"{base}/events/{ev['id']}/photo-finder/search", headers=fan, files=selfie, data={"consent": "false"}).status_code == 400
    res = client.post(f"{base}/events/{ev['id']}/photo-finder/search", headers=fan, files=selfie, data={"consent": "true"})
    assert res.status_code == 200, res.text
    assert len(res.json()["matches"]) == 1 and res.json()["searched"] == 2

    first = up.json()[0]["id"]
    assert client.delete(f"{base}/manage/events/{ev['id']}/photos/{first}", headers=club_admin).status_code == 204
    assert len(client.get(f"{base}/manage/events/{ev['id']}/photos", headers=club_admin).json()) == 1


def test_photo_finder_com_colecao_e_bucket_configurados(client, club_admin, fan, monkeypatch):
    """Com a coleção e o bucket configurados, a busca devolve links temporários do S3 (sem fotos enviadas ao show)."""
    from app import rekognition
    from app.config import get_settings

    cfg = get_settings()
    monkeypatch.setattr(cfg, "rekognition_enabled", True)
    monkeypatch.setattr(cfg, "rekognition_collection_id", "colecao-teste")
    monkeypatch.setattr(cfg, "s3_bucket", "bucket-teste")
    monkeypatch.setattr(rekognition, "search_shared", lambda data: ["abc123", "fotos/x/def456.jpg"])
    monkeypatch.setattr(rekognition, "presigned_photos", lambda ids: [(i, f"https://s3.example/{rekognition.photo_key(i)}?assinado=1") for i in ids])
    assert rekognition.photo_key("abc123") == "photos/original/abc123.jpg"
    assert rekognition.photo_key("fotos/x/def456.jpg") == "fotos/x/def456.jpg"

    base = "/artists/vintage-culture"
    png = bytes([137]) + b"PNG" + bytes([13, 10, 26, 10]) + b"0" * 32
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2020-02-05", "city": "Passado 2"}).json()
    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Agência Passado 2"}).json()
    pkg = client.post(
        f"{base}/manage/packages", headers=club_admin,
        json={"eventId": ev["id"], "agencyId": ag["id"], "name": "Caravana", "addons": [{"key": "camarim", "priceCents": 29000}]},
    ).json()
    assert client.post(f"{base}/events/{ev['id']}/purchases", headers=fan, json={"packageId": pkg["id"], "addons": ["camarim"], "ticketOptin": True}).status_code == 201
    st = client.get(f"{base}/events/{ev['id']}/photo-finder", headers=fan).json()
    assert st["eligible"] is True and st["photos"] == 0  # não precisa de fotos enviadas ao show
    res = client.post(f"{base}/events/{ev['id']}/photo-finder/search", headers=fan, files={"selfie": ("eu.png", png, "image/png")}, data={"consent": "true"})
    assert res.status_code == 200, res.text
    urls = [m["src"] for m in res.json()["matches"]]
    assert urls == ["https://s3.example/photos/original/abc123.jpg?assinado=1", "https://s3.example/fotos/x/def456.jpg?assinado=1"]


def test_ingresso_com_photo_finder_automatico_na_demonstracao(client, club_admin, fan, monkeypatch):
    from app.config import get_settings

    base = "/artists/vintage-culture"
    client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2019-03-05", "city": "Show Antigo"})
    antes = client.get(f"{base}/me/tickets", headers=fan).json()
    n_antes = len(antes)
    monkeypatch.setattr(get_settings(), "demo_photo_ticket", True)
    depois = client.get(f"{base}/me/tickets", headers=fan).json()
    assert len(depois) > n_antes and all(t["includesPhotoFinder"] for t in depois)
    # rodar de novo não duplica
    assert len(client.get(f"{base}/me/tickets", headers=fan).json()) == len(depois)


def test_experiencias_extras_com_optin_e_photo_finder_em_todas(client, club_admin, fan):
    base = "/artists/vintage-culture"
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2031-05-10", "city": "Recife"}).json()
    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Agência Recife"}).json()
    addons = [{"key": "jantar", "priceCents": 45000}, {"key": "hotel", "priceCents": 38000}, {"key": "after", "priceCents": 18000, "soldOut": True}]
    pkg = client.post(
        f"{base}/manage/packages", headers=club_admin,
        json={"eventId": ev["id"], "agencyId": ag["id"], "name": "Caravana", "addons": addons},
    )
    assert pkg.status_code == 201 and [a["key"] for a in pkg.json()["addons"]] == ["jantar", "hotel", "after"]
    assert client.post(f"{base}/manage/packages", headers=club_admin, json={"eventId": ev["id"], "agencyId": ag["id"], "name": "X", "addons": [{"key": "spa", "priceCents": 1}], "items": []}).status_code == 422
    pid = pkg.json()["id"]
    listados = client.get(f"{base}/events/{ev['id']}/packages", headers=fan).json()[0]["addons"]
    assert listados[0] == {"key": "jantar", "label": "Jantar com o Vintage", "priceCents": 45000, "soldOut": False}

    url = f"{base}/events/{ev['id']}/purchases"
    ok = {"packageId": pid, "ticketOptin": True}
    assert client.post(url, headers=fan, json={**ok, "addons": ["after"]}).status_code == 400  # esgotado
    assert client.post(url, headers=fan, json={**ok, "addons": ["camarim"]}).status_code == 400  # fora do pacote
    assert client.post(url, headers=fan, json={**ok, "addons": []}).status_code == 400  # precisa de ao menos uma
    compra = client.post(url, headers=fan, json={**ok, "addons": ["jantar", "hotel", "jantar"]})
    assert compra.status_code == 201, compra.text
    c = compra.json()
    # só as experiências: o ingresso (Pista) é da Ingresse e não entra no valor nem no rótulo
    assert c["priceCents"] == 45000 + 38000 and c["label"] == "Jantar com o Vintage + Hotel com hospedagem"
    assert c["kind"] == "experience" and c["includesPhotoFinder"] is True


def test_compra_de_experiencias_exige_optin_da_ingresse(client, club_admin, fan):
    from app import models as m
    from app.db import SessionLocal

    base = "/artists/vintage-culture"
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2031-07-10", "city": "Maceió"}).json()
    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Agência Maceió"}).json()
    pkg = client.post(
        f"{base}/manage/packages", headers=club_admin,
        json={"eventId": ev["id"], "agencyId": ag["id"], "name": "Caravana", "items": [], "addons": [{"key": "pre", "priceCents": 12000}]},
    ).json()
    url = f"{base}/events/{ev['id']}/purchases"
    body = {"packageId": pkg["id"], "addons": ["pre"]}
    # a cotação não pede a confirmação (o fã vê o valor antes de marcar)
    assert client.post(f"{base}/events/{ev['id']}/quote", headers=fan, json=body).json()["totalCents"] == 12000
    # sem a confirmação (ausente ou falsa), a compra é recusada
    sem = client.post(url, headers=fan, json=body)
    assert sem.status_code == 422 and "Ingresse" in sem.json()["detail"]
    assert client.post(url, headers=fan, json={**body, "ticketOptin": False}).status_code == 422
    antes = len(client.get(f"{base}/me/tickets", headers=fan).json())
    compra = client.post(url, headers=fan, json={**body, "ticketOptin": True})
    assert compra.status_code == 201, compra.text
    assert len(client.get(f"{base}/me/tickets", headers=fan).json()) == antes + 1
    with SessionLocal() as db:
        assert db.get(m.TicketPurchase, compra.json()["id"]).ticket_optin_at is not None


def test_cupom_de_desconto_na_compra(client, club_admin, fan, monkeypatch):
    from app.config import get_settings

    base = "/artists/vintage-culture"
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2031-06-10", "city": "Salvador"}).json()
    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Agência Salvador"}).json()
    pkg = client.post(
        f"{base}/manage/packages", headers=club_admin,
        json={"eventId": ev["id"], "agencyId": ag["id"], "name": "Caravana", "addons": [{"key": "jantar", "priceCents": 100000}]},
    ).json()
    body = {"packageId": pkg["id"], "addons": ["jantar"], "ticketOptin": True}
    q = f"{base}/events/{ev['id']}/quote"
    assert client.post(q, headers=fan, json=body).json()["totalCents"] == 100000

    # cupom geral criado pela administração (código em maiúsculas), 20%
    cp = client.post(f"{base}/manage/coupons", headers=club_admin, json={"code": "vintage20", "kind": "percent", "value": 20, "maxUses": 1})
    assert cp.status_code == 201 and cp.json()["code"] == "VINTAGE20"
    assert client.post(f"{base}/manage/coupons", headers=club_admin, json={"code": "ZERO", "kind": "percent", "value": 150}).status_code == 400
    r = client.post(q, headers=fan, json={**body, "coupon": " vintage20 "}).json()
    assert (r["subtotalCents"], r["discountCents"], r["totalCents"], r["coupon"], r["couponLabel"]) == (100000, 20000, 80000, "VINTAGE20", "20% de desconto")
    assert client.post(q, headers=fan, json={**body, "coupon": "NAOEXISTE"}).status_code == 400

    # cupom pessoal da roleta (demonstração): aparece em "meus cupons" e vale só uma vez
    assert client.get(f"{base}/me/coupons", headers=fan).json() == []
    monkeypatch.setattr(get_settings(), "demo_photo_ticket", True)
    meus = client.get(f"{base}/me/coupons", headers=fan).json()
    assert [c["code"] for c in meus] == ["ROLETA10"] and meus[0]["label"] == "10% de desconto" and meus[0]["source"].startswith("Prêmio da roleta")
    compra = client.post(f"{base}/events/{ev['id']}/purchases", headers=fan, json={**body, "coupon": "ROLETA10"})
    assert compra.status_code == 201 and compra.json()["priceCents"] == 90000
    assert client.get(f"{base}/me/coupons", headers=fan).json() == []
    assert client.post(q, headers=fan, json={**body, "coupon": "ROLETA10"}).status_code == 400  # uso único
    # o cupom geral de uso único também esgota depois de usado
    assert client.post(f"{base}/events/{ev['id']}/purchases", headers=fan, json={**body, "coupon": "VINTAGE20"}).json()["priceCents"] == 80000
    assert client.post(q, headers=fan, json={**body, "coupon": "VINTAGE20"}).status_code == 400


def test_brindes_da_roleta_guardados_em_meus_brindes(client, club_admin, fan):
    base = "/artists/vintage-culture"
    club = f"{base}/clubs/oficial"
    # roleta só com brindes de cada tipo: sai o sorteado, e o servidor guarda o brinde com código e instruções
    atuais = client.get(f"{club}/manage/prizes", headers=club_admin).json()
    for p in atuais:
        client.delete(f"{club}/manage/prizes/{p['id']}", headers=club_admin)

    def monta(label, kind, percent=0):
        r = client.post(f"{club}/manage/prizes", headers=club_admin, json={"label": label, "kind": kind, "percent": percent})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def gira():
        creditos = [g for g in client.get(f"{base}/pickup/spins", headers=fan).json() if not g["used"]]
        assert creditos, "o fã precisa de um giro"
        return client.post(f"{club}/pickup/spin", headers=fan, json={"creditId": creditos[0]["id"]})

    def apaga_todas():
        for p in client.get(f"{club}/manage/prizes", headers=club_admin).json():
            client.delete(f"{club}/manage/prizes/{p['id']}", headers=club_admin)

    antes = len(client.get(f"{base}/me/rewards", headers=fan).json())  # outros testes já giraram com este fã
    monta("Não foi dessa vez", "none")
    r = gira()
    assert r.status_code == 200 and r.json()["prize"]["kind"] == "none" and r.json()["reward"] is None
    assert len(client.get(f"{base}/me/rewards", headers=fan).json()) == antes

    apaga_todas()
    monta("20% no ingresso", "coupon", 20)
    r = gira().json()
    assert r["prize"]["kind"] == "coupon" and r["reward"]["kind"] == "coupon" and r["reward"]["couponCode"].startswith("ROLETA20-")
    cupom = r["reward"]["couponCode"]
    assert cupom in [c["code"] for c in client.get(f"{base}/me/coupons", headers=fan).json()]  # já aparece em Meus cupons

    apaga_todas()
    monta("Boné Vintage", "pickup")
    r = gira().json()
    rw = r["reward"]
    assert rw["kind"] == "pickup" and rw["status"] == "available" and "lojinha" in rw["instructions"] and len(rw["code"]) == 5

    meus = client.get(f"{base}/me/rewards", headers=fan).json()
    assert [b["label"] for b in meus][:2] == ["Boné Vintage", "20% no ingresso"] and len(meus) == antes + 2

    # a equipe dá baixa na retirada; não retira duas vezes e o fã não pode dar baixa
    assert client.post(f"{base}/manage/rewards/{rw['code']}/redeem", headers=fan).status_code == 403
    ok = client.post(f"{base}/manage/rewards/{rw['code'].lower()}/redeem", headers=club_admin)
    assert ok.status_code == 200 and ok.json()["status"] == "redeemed"
    assert client.post(f"{base}/manage/rewards/{rw['code']}/redeem", headers=club_admin).status_code == 400
    assert client.post(f"{base}/manage/rewards/ZZZZZ/redeem", headers=club_admin).status_code == 404
    assert client.get(f"{base}/me/rewards", headers=fan).json()[0]["status"] == "redeemed"


def test_post_do_fa_com_texto_e_foto(client, fan):
    base = "/artists/vintage-culture"
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    url = f"{base}/clubs/oficial/posts/media"
    so_texto = client.post(url, headers=fan, data={"text": "Só texto"})
    assert so_texto.status_code == 201 and so_texto.json()["image"] is None and so_texto.json()["club"]["slug"] == "oficial"
    com_foto = client.post(url, headers=fan, data={"text": "Com foto"}, files={"image": ("a.png", png, "image/png")})
    assert com_foto.status_code == 201 and com_foto.json()["image"]["src"].startswith("/uploads/")
    assert client.post(url, headers=fan, data={"text": "x"}, files={"image": ("a.gif", b"G", "image/gif")}).status_code == 400
    assert client.post(url, headers=fan, data={"text": ""}).status_code == 422
    assert client.post(f"{base}/clubs/nao-existe/posts/media", headers=fan, data={"text": "x"}).status_code == 404


def test_ranking_fa_super_com_instagram_simulado(client, club_admin, fan, monkeypatch):
    from sqlalchemy import select

    from app import instagram, models as m
    from app.db import SessionLocal

    base = "/artists/vintage-culture"
    post = client.get(f"{base}/posts?kind=drop", headers=fan).json()[0]
    # só post oficial pode ser compartilhado; post de fã não
    galera = client.get(f"{base}/posts?kind=galera", headers=fan).json()[0]
    assert client.post(f"{base}/posts/{galera['id']}/share", headers=fan).status_code == 400

    sh = client.post(f"{base}/posts/{post['id']}/share", headers=fan)
    assert sh.status_code == 201, sh.text
    out = sh.json()
    assert out["hashtag"] == "EuSouUmSuperFaDoVintage" and out["code"].startswith("FS-") and f"#{out['hashtag']} {out['code']}" in out["caption"]
    # "já postei": rende 1 giro na hora e o compartilhamento fica aguardando a conferência
    antes = sum(1 for g in client.get(f"{base}/pickup/spins", headers=fan).json() if not g["used"])
    cl = client.post(f"{base}/shares/{out['shareId']}/claim", headers=fan)
    assert cl.status_code == 200 and cl.json()["spinGranted"] is True
    depois = client.get(f"{base}/pickup/spins", headers=fan).json()
    assert sum(1 for g in depois if not g["used"]) == antes + 1 and any(g["reason"].startswith("Compartilhou no Instagram") for g in depois)
    assert client.post(f"{base}/shares/{out['shareId']}/claim", headers=fan).json()["already"] is True  # só conta uma vez
    assert client.post(f"{base}/shares/nao-existe/claim", headers=fan).status_code == 404
    track = client.get(f"{base}/tracks", headers=fan).json()[0]
    ts = client.post(f"{base}/tracks/{track['id']}/share", headers=fan)
    assert ts.status_code == 201 and ts.json()["caption"].startswith(track["title"]) and ts.json()["hashtag"] == out["hashtag"]
    assert client.post(f"{base}/tracks/nao-existe/share", headers=fan).status_code == 404
    me = client.get(f"{base}/ranking", headers=fan).json()
    assert me["me"]["pending"] >= 1 and me["me"]["position"] is None and me["myCode"] == out["code"]

    media = [
        {"id": "ig-1", "caption": f"Amei! #eusouumsuperfadovintage {out['code']}", "permalink": "https://instagram.com/p/abc"},
        {"id": "ig-2", "caption": f"sem a hashtag {out['code']}"},  # sem hashtag: não conta
        {"id": "ig-3", "caption": "#EuSouUmSuperFaDoVintage FS-ZZZZZ"},  # código desconhecido
    ]
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        r = instagram.sync(db, artist, media)
        assert r.found == 3 and r.verified == 1
        assert instagram.sync(db, artist, media).verified == 0  # o mesmo post não pontua duas vezes

    rank = client.get(f"{base}/ranking", headers=fan).json()
    assert rank["me"]["position"] == 1 and rank["me"]["shares"] == 1 and rank["top"][0]["me"] is True
    oficial = next(c for c in rank["clubs"] if c["slug"] == "oficial")
    assert oficial["me"]["position"] == 1 and oficial["top"][0]["me"] is True  # ranking do fã clube

    off = client.post(f"{base}/manage/instagram/sync", headers=club_admin).json()
    assert off["enabled"] is False  # sem credenciais da Meta
    assert client.post(f"{base}/manage/instagram/sync", headers=fan).status_code == 403


def test_perfil_do_fa(client, fan):
    p = client.get("/auth/profile", headers=fan)
    assert p.status_code == 200
    body = p.json()
    assert body["email"] == "fa@superfas.dev" and "zipCode" in body and "since" in body
    assert client.get("/auth/profile").status_code == 401


def test_giros_por_post_e_por_camiseta(client, club_admin, fan):
    base = "/artists/vintage-culture"

    def livres():
        return sum(1 for g in client.get(f"{base}/pickup/spins", headers=fan).json() if not g["used"])

    antes = livres()
    # posts rendem 1 giro cada, até 3 por dia
    rendeu = []
    for i in range(5):
        r = client.post(f"{base}/clubs/oficial/posts/media", headers=fan, data={"text": f"Post {i}"})
        assert r.status_code == 201
        rendeu.append(r.json()["rewardSpin"])
    # o fã já pode ter postado antes (em outros testes): o teto é 3 giros por dia, então sobram pelo menos 2 sem giro
    assert sum(rendeu) <= 3 and rendeu.count(False) >= 2
    assert livres() == antes + sum(rendeu)
    motivos = [g["reason"] for g in client.get(f"{base}/pickup/spins", headers=fan).json()]
    assert any(x.startswith("Post publicado em") for x in motivos) or sum(rendeu) == 0

    # camiseta (roupas) rende giro; acessório não
    camiseta = client.post(f"{base}/manage/products", headers=club_admin, json={"name": "Camiseta Teste", "category": "roupas", "priceCents": 12000}).json()
    outro = client.post(f"{base}/manage/products", headers=club_admin, json={"name": "Boné Teste", "category": "acessorios", "priceCents": 8000}).json()
    base_livres = livres()
    itens = [{"productId": camiseta["id"], "qty": 2, "size": "m"}, {"productId": outro["id"], "qty": 1}]
    quote = client.post(f"{base}/store/quote", headers=fan, json={"items": itens})
    assert quote.status_code == 200, quote.text
    q = quote.json()
    assert q["subtotalCents"] == 2 * 12000 + 8000 and q["shippingCents"] == 0 and q["totalCents"] == 32000  # retirada na lojinha não paga frete
    assert [l["size"] for l in q["lines"]] == ["M", ""]  # tamanho só nas roupas

    # entrega: frete fixo abaixo de R$ 300, grátis a partir daí, e o endereço é obrigatório
    pequeno = [{"productId": outro["id"], "qty": 1}]
    assert client.post(f"{base}/store/quote", headers=fan, json={"items": pequeno, "delivery": "ship"}).status_code == 400
    ship = client.post(f"{base}/store/quote", headers=fan, json={"items": pequeno, "delivery": "ship", "address": "Rua das Flores, 100, Campinas"}).json()
    assert ship["shippingCents"] == 1990 and ship["totalCents"] == 8000 + 1990
    assert client.post(f"{base}/store/quote", headers=fan, json={"items": itens, "delivery": "ship", "address": "Rua das Flores, 100, Campinas"}).json()["shippingCents"] == 0

    # roupa sem tamanho e produto inexistente
    assert client.post(f"{base}/store/quote", headers=fan, json={"items": [{"productId": camiseta["id"], "qty": 1}]}).status_code == 400
    assert client.post(f"{base}/store/checkout", headers=fan, json={"items": [{"productId": "nao-existe", "qty": 1}]}).status_code == 404

    ck = client.post(f"{base}/store/checkout", headers=fan, json={"items": itens})
    assert ck.status_code == 201, ck.text
    c = ck.json()
    assert c["spinsGranted"] == 2 and c["items"] == 3 and c["totalCents"] == 32000 and c["orderCode"].startswith("LJ-")  # 1 giro por camiseta (qty 2)
    assert livres() == base_livres + 2
    pedidos = client.get(f"{base}/me/orders", headers=fan).json()
    assert pedidos[0]["code"] == c["orderCode"] and pedidos[0]["totalCents"] == 32000 and [l["qty"] for l in pedidos[0]["lines"]] == [2, 1]


def test_selo_de_dono_do_fa_clube_nos_posts(client, club_admin, fan):
    base = "/artists/vintage-culture"
    club_posts = f"{base}/clubs/oficial/posts"
    dono = client.post(club_posts, headers=club_admin, json={"text": "Aviso do dono"}).json()
    assert dono["author"]["badge"] == "Dono do fã clube"
    comum = client.post(f"{club_posts}/media", headers=fan, data={"text": "Post de fã"}).json()
    assert comum["author"]["badge"] is None
    feed = client.get(f"{base}/posts", headers=fan).json()
    assert next(p for p in feed if p["id"] == dono["id"])["author"]["badge"] == "Dono do fã clube"


def test_dono_do_fa_clube_aparece_no_proprio_ranking(client, club_admin):
    rk = client.get("/artists/vintage-culture/ranking", headers=club_admin).json()
    oficial = next(c for c in rk["clubs"] if c["slug"] == "oficial")
    assert oficial["me"] is not None  # o dono é parte do fã clube, mesmo sem entrar como membro


def test_admin_define_quem_lidera_o_ranking(client, club_admin, fan):
    base = "/artists/vintage-culture"
    eu = client.get("/auth/me", headers=fan).json()
    antes = client.get(f"{base}/ranking", headers=fan).json()["me"]["position"]
    scopes = client.get(f"{base}/manage/ranking", headers=club_admin).json()
    assert scopes[0]["clubSlug"] is None and scopes[0]["leader"] is None
    assert client.get(f"{base}/manage/ranking", headers=fan).status_code == 403  # só a administração

    # o fã de teste não tem compartilhamento, mas a administração o coloca em 1º no geral
    achados = client.get(f"{base}/manage/ranking/fans", params={"q": eu["name"][:4]}, headers=club_admin).json()
    alvo = next(f for f in achados if f["userId"] == eu["id"])
    r = client.put(f"{base}/manage/ranking/leader", json={"userId": alvo["userId"]}, headers=club_admin)
    assert r.status_code == 200 and r.json()["leader"]["userId"] == eu["id"]
    rk = client.get(f"{base}/ranking", headers=fan).json()
    assert rk["top"][0]["me"] is True and rk["me"]["position"] == 1
    geral = client.get(f"{base}/manage/ranking", headers=club_admin).json()[0]
    hist = client.get(f"{base}/manage/ranking/people/{eu['id']}", headers=club_admin).json()
    assert hist["name"] == eu["name"] and hist["position"] == 1 and isinstance(hist["posts"], list)
    assert all(sh["rankingPoints"] == 0 or sh["rankingPoints"] >= 1 for sh in hist["shares"])
    assert abs(hist["points"] - sum(sh["rankingPoints"] for sh in hist["shares"])) < 0.01 and hist["sharesConfirmed"] == sum(1 for sh in hist["shares"] if sh["rankingPoints"])
    assert client.get(f"{base}/manage/ranking/people/{eu['id']}", headers=fan).status_code == 403
    assert client.get(f"{base}/manage/ranking/people/nao-existe", headers=club_admin).status_code == 404
    assert geral["people"][0]["name"] == eu["name"] and geral["people"][0]["position"] == 1 and len(geral["people"]) <= 10

    # fã de fora do fã clube não pode ser fixado nele; desfazer volta ao placar
    assert client.put(f"{base}/manage/ranking/leader", json={"userId": "nao-existe"}, headers=club_admin).status_code == 404
    assert client.put(f"{base}/manage/ranking/leader", json={"clubSlug": "nao-existe", "userId": eu["id"]}, headers=club_admin).status_code == 404
    assert client.put(f"{base}/manage/ranking/leader", json={}, headers=club_admin).json()["leader"] is None
    assert client.get(f"{base}/ranking", headers=fan).json()["me"]["position"] == antes


def test_analytics_do_clube_traz_o_card_do_dono(client, club_admin):
    base = "/artists/vintage-culture"
    r = client.get(f"{base}/clubs/oficial/analytics", headers=club_admin).json()
    assert r["owner"]["email"] and r["owner"]["name"] and r["owner"]["points"] >= 0 and "avatar" in r["owner"]
    assert "ownerAvatar" in r["club"]
    assert "ownerAvatar" in client.get(f"{base}/clubs-overview", headers=club_admin).json()[0]


def test_destaques_dos_fa_clubes(client, club_admin, fan):
    base = "/artists/vintage-culture"
    rows = client.get(f"{base}/clubs-highlights", headers=club_admin).json()
    assert rows and {"content", "buzz", "members", "activeMembers", "activeRate"} <= set(rows[0])
    assert all(0 <= r["activeRate"] <= 100 and r["content"] == r["posts"] + r["prizes"] for r in rows)
    assert client.get(f"{base}/clubs-highlights", headers=fan).status_code == 403


def test_vitrines_alugadas(client, club_admin, sponsor, fan):
    from datetime import date, timedelta

    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal

    base = "/artists/vintage-culture"
    today = date.today()
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        env_slot = next(s for s in artist.ad_slots if s.club_id is None)
        club_slot = next(s for s in artist.ad_slots if s.club_id is not None)
        env_slot.price_cents = 50000
        sp = db.scalar(select(m.Sponsor).where(m.Sponsor.email == "marca@superfas.dev"))
        for slot, start, end, status in [
            (env_slot, today - timedelta(days=3), today + timedelta(days=10), "approved"),  # no ar (14 dias = 2 semanas)
            (club_slot, today + timedelta(days=5), today + timedelta(days=11), "approved"),  # agendada
            (env_slot, today - timedelta(days=40), today - timedelta(days=30), "approved"),  # encerrada
            (env_slot, today, today + timedelta(days=7), "pending"),  # pendente: não é aluguel
        ]:
            db.add(m.Campaign(sponsor_id=sp.id, slot_id=slot.id, brand="Marca Teste", title="Anúncio", start=start, end=end, status=status))
        db.commit()
    r = client.get(f"{base}/rentals", headers=club_admin)
    assert r.status_code == 200, r.text
    rows = [x for x in r.json() if x["title"] == "Anúncio"]  # outros testes também aprovam campanhas
    assert [x["status"] for x in rows] == ["live", "scheduled", "ended"]
    live = rows[0]
    assert "diagramTop" in live and live["diagramHeight"] > 0
    assert live["sponsor"] == "Marca Teste" and live["days"] == 14 and live["estimatedTotalCents"] == 100000 and live["fanClub"] is None
    assert rows[1]["fanClub"] is not None
    assert client.get(f"{base}/rentals", headers=fan).status_code == 403


# ---------------------------------------------------------------- anúncios dentro do app


def test_vitrines_do_app_em_ambiente_novo(client, master):
    slug = client.post("/admin/fan-clubs", headers=master, json={"name": "Artista Anúncios"}).json()["artist"]["slug"]
    slots = {s["id"]: s for s in client.get(f"/artists/{slug}/ad-slots", headers=master).json()}
    assert {"entrada", "pickup_video", "pickup_resgate", "mural", "home"} <= set(slots)
    assert slots["mural"]["where"] == "Mural · post pequeno entre os cartazes, a cada 4"
    assert slots["pickup_video"]["name"] == "Vídeo antes do giro"


def test_migracao_cria_vitrines_que_faltam():
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal, engine
    from app.migrations import upgrade

    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        for s in list(artist.ad_slots):
            if s.key == "pickup_resgate":
                db.delete(s)
            if s.key == "mural":
                s.where = "Mural · aba Galera, a cada [n] posts"
        db.commit()
    upgrade(engine)
    upgrade(engine)  # idempotente
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        env = [s for s in artist.ad_slots if s.club_id is None]
        assert [s.key for s in env].count("pickup_resgate") == 1
        resgate = next(s for s in env if s.key == "pickup_resgate")
        assert resgate.position == max(s.position for s in env)
        assert next(s for s in env if s.key == "mural").where == "Mural · post pequeno entre os cartazes, a cada 4"


def test_anuncios_dentro_do_app(client, master, sponsor, fan):
    empty = {"entry": None, "pickupVideo": None, "pickupClaim": None, "feed": None}
    r = client.get(f"{VC}/ads/in-app", headers=fan)
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in ("pickupVideo", "pickupClaim", "entry")} == {k: None for k in ("pickupVideo", "pickupClaim", "entry")}

    today = date.today()
    form = {
        "club": "vintage-culture", "slot": "pickup_video", "brand": "Bebida Teste", "title": "Gire com sabor",
        "text": "Assista e gire", "link": "https://exemplo.com", "start": today.isoformat(), "end": (today + timedelta(days=7)).isoformat(),
    }
    # vitrine de vídeo sem vídeo
    r = client.post("/sponsor/campaigns", headers=sponsor, data=form)
    assert r.status_code == 400 and "vídeo" in r.json()["detail"]
    # link inválido
    r = client.post("/sponsor/campaigns", headers=sponsor, data={**form, "video_url": "javascript:alert(1)"})
    assert r.status_code == 400
    # arquivo em formato errado
    r = client.post("/sponsor/campaigns", headers=sponsor, data=form, files={"video": ("v.avi", b"x" * 10, "video/x-msvideo")})
    assert r.status_code == 400

    r = client.post("/sponsor/campaigns", headers=sponsor, data={**form, "video_url": "https://cdn.exemplo.com/v.mp4"})
    assert r.status_code == 201, r.text
    camp = r.json()
    assert camp["videoUrl"] == "https://cdn.exemplo.com/v.mp4"
    assert client.get(f"{VC}/ads/in-app", headers=fan).json()["pickupVideo"] is None  # pendente
    client.post(f"/campaigns/{camp['id']}/approve", headers=master)

    ads = client.get(f"{VC}/ads/in-app", headers=fan).json()
    v = ads["pickupVideo"]
    assert v["id"] == camp["id"] and v["minSeconds"] is None and v["videoUrl"] == "https://cdn.exemplo.com/v.mp4"
    assert v["sponsor"] == "Bebida Teste" and v["imageUrl"] is None and v["cta"] == "Saiba mais"
    assert ads["entry"] is None
    assert any(c["videoUrl"] for c in client.get("/admin/campaigns", headers=master).json())

    # upload do vídeo
    r = client.post("/sponsor/campaigns", headers=sponsor, data=form, files={"video": ("v.mp4", b"\x00" * 64, "video/mp4")})
    assert r.status_code == 201, r.text
    assert r.json()["videoUrl"].startswith("/uploads/") and r.json()["videoUrl"].endswith(".mp4")

    # módulo de anúncios desligado: tudo null
    client.patch("/admin/fan-clubs/vintage-culture", headers=master, json={"modules": {"ads": False}})
    try:
        assert client.get(f"{VC}/ads/in-app", headers=fan).json() == empty
    finally:
        client.patch("/admin/fan-clubs/vintage-culture", headers=master, json={"modules": {"ads": True}})


def test_lista_de_assinantes_pagina_busca_e_acoes(client, club_admin, fan):
    base = "/artists/vintage-culture"
    pg = client.get(f"{base}/subscribers", headers=club_admin).json()
    assert pg["pageSize"] == 10 and len(pg["items"]) <= 10 and pg["page"] == 1 and pg["total"] >= len(pg["items"])
    assert client.get(f"{base}/subscribers", headers=fan).status_code == 403
    since = [i["since"] for i in pg["items"] if i["since"]]
    assert since == sorted(since, reverse=True)  # do que assinou por último para o primeiro
    if pg["items"]:
        first = pg["items"][0]
        achado = client.get(f"{base}/subscribers", params={"q": first["name"][:3].upper()}, headers=club_admin).json()
        assert any(i["userId"] == first["userId"] for i in achado["items"])
        assert client.get(f"{base}/subscribers", params={"q": "zzzzzzzzzz"}, headers=club_admin).json()["total"] == 0
        act = client.get(f"{base}/subscribers/{first['userId']}/activity", headers=club_admin).json()
        assert act["profile"]["userId"] == first["userId"] and {"spinsUsed", "couponsUsed", "purchases"} <= set(act["summary"])
        ats = [e["at"] for e in act["events"]]
        assert ats == sorted(ats, reverse=True)
    assert client.get(f"{base}/subscribers/nao-existe/activity", headers=club_admin).status_code == 404


def test_pickup_admin_roleta_historico_estoque_e_ganhadores(client, club_admin, fan):
    base = "/artists/vintage-culture"
    ov = client.get(f"{base}/manage/pickup", headers=club_admin).json()
    assert ov["wheel"]["isMaster"] is True and ov["prizes"] and {"spins", "spinners", "spinsLeft", "rewards"} <= set(ov["summary"])
    assert client.get(f"{base}/manage/pickup", headers=fan).status_code == 403
    assert client.get(f"{base}/manage/pickup", params={"club": "nao-existe"}, headers=club_admin).status_code == 404

    # estoque: só a fatia que tem unidades sobrando pode sair
    slug = ov["wheel"]["slug"]
    prizes = client.get(f"{base}/clubs/{slug}/manage/prizes", headers=club_admin).json()
    assert all("stock" in p for p in prizes)
    for p in prizes:  # zera o estoque de todas, menos de uma fatia comum
        keep = p["id"] == prizes[0]["id"]
        client.patch(f"{base}/clubs/{slug}/manage/prizes/{p['id']}", json={"stock": 5 if keep else 0}, headers=club_admin)
    out = client.post(f"{base}/pickup/spin", headers=fan)
    if out.status_code == 200:  # o fã de teste pode estar sem giros
        assert out.json()["prize"]["id"] == prizes[0]["id"]
        hist = client.get(f"{base}/manage/pickup/history", headers=club_admin).json()
        assert hist["pageSize"] == 10 and hist["total"] >= 1 and hist["items"][0]["prize"]
        assert hist["items"][0]["at"] >= hist["items"][-1]["at"]
        w = client.get(f"{base}/manage/pickup/prizes/{prizes[0]['id']}/winners", headers=club_admin).json()
        assert w["total"] >= 1 and w["pageSize"] == 10
    assert client.get(f"{base}/manage/pickup/prizes/nao-existe/winners", headers=club_admin).status_code == 404
    for p in prizes:  # volta ao ilimitado
        client.patch(f"{base}/clubs/{slug}/manage/prizes/{p['id']}", json={"stock": None}, headers=club_admin)


def test_detalhes_de_post_e_de_hit_no_admin(client, club_admin, fan):
    base = "/artists/vintage-culture"
    drop = client.get(f"{base}/posts?kind=drop", headers=fan).json()[0]
    d = client.get(f"{base}/manage/posts/{drop['id']}/detail", headers=club_admin).json()
    assert d["id"] == drop["id"] and {"likes", "comments", "views", "sharesTotal", "commentList", "shares"} <= set(d)
    assert client.get(f"{base}/manage/posts/{drop['id']}/detail", headers=fan).status_code == 403
    assert client.get(f"{base}/manage/posts/nao-existe/detail", headers=club_admin).status_code == 404
    track = client.get(f"{base}/tracks", headers=fan).json()[0]
    t = client.get(f"{base}/manage/tracks/{track['id']}/detail", headers=club_admin).json()
    assert t["id"] == track["id"] and {"likes", "views", "sharesTotal", "shares"} <= set(t)
    assert client.get(f"{base}/manage/tracks/nao-existe/detail", headers=club_admin).status_code == 404


def test_mapa_das_vitrines_admin_e_patrocinador(client, club_admin, sponsor, fan):
    base = "/artists/vintage-culture"
    mp = client.get(f"{base}/vitrines-map", headers=club_admin).json()
    groups = {c["group"] for c in mp["cards"]}
    assert {"entrada", "roleta", "feed"} <= groups
    keys = {c["key"] for c in mp["cards"]}
    assert {"entrada", "pickup_video", "pickup_resgate", "mural", "feed_2", "feed_3", "feed_4"} <= keys
    assert any(c["clubSlug"] and c["group"] == "feed" for c in mp["cards"])  # feeds dos fã clubes
    order = [c["group"] for c in mp["cards"]]
    assert order == sorted(order, key=lambda g: {"entrada": 0, "roleta": 1, "feed": 2, "outras": 3}[g])
    assert client.get(f"{base}/vitrines-map", headers=fan).status_code == 403
    sp = client.get("/sponsor/vitrines-map", params={"artist": "vintage-culture"}, headers=sponsor).json()
    assert len(sp["cards"]) == len(mp["cards"])
    assert client.get("/sponsor/vitrines-map", params={"artist": "vintage-culture"}, headers=fan).status_code == 403


def test_lista_de_compradores_das_experiencias(client, club_admin, fan):
    base = "/artists/vintage-culture"
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": "2032-03-10", "city": "Maceió"}).json()
    ag = client.post(f"{base}/manage/agencies", headers=club_admin, json={"name": "Agência Maceió"}).json()
    pkg = client.post(
        f"{base}/manage/packages", headers=club_admin,
        json={"eventId": ev["id"], "agencyId": ag["id"], "name": "Experiências Maceió", "addons": [{"key": "jantar", "priceCents": 45000}, {"key": "hotel", "priceCents": 38000}]},
    ).json()
    assert client.post(f"{base}/events/{ev['id']}/purchases", headers=fan, json={"packageId": pkg["id"], "addons": ["jantar", "hotel"], "ticketOptin": True}).status_code == 201
    ov = client.get(f"{base}/manage/events/{ev['id']}/experiences", headers=club_admin).json()
    por = {x["key"]: x for x in ov["experiences"]}
    assert ov["purchases"] == 1 and ov["people"] == 1 and ov["revenueCents"] == 83000
    assert por["jantar"]["purchases"] == 1 and por["jantar"]["offeredIn"] == ["Experiências Maceió"] and por["hotel"]["people"] == 1
    b = client.get(f"{base}/manage/events/{ev['id']}/experiences/jantar/buyers", headers=club_admin).json()
    assert b["total"] == 1 and b["pageSize"] == 10 and b["label"] == "Jantar com o Vintage"
    assert b["items"][0]["experiences"] == ["Jantar com o Vintage", "Hotel com hospedagem"] and b["items"][0]["paidCents"] == 83000
    assert client.get(f"{base}/manage/events/{ev['id']}/experiences/jantar/buyers", params={"q": "zzzzzz"}, headers=club_admin).json()["total"] == 0
    assert client.get(f"{base}/manage/events/{ev['id']}/experiences/camarim/buyers", headers=club_admin).json()["total"] == 0
    assert client.get(f"{base}/manage/events/{ev['id']}/experiences", headers=fan).status_code == 403
    assert client.get(f"{base}/manage/events/nao-existe/experiences", headers=club_admin).status_code == 404


def test_anuncios_do_feed(client, fan):
    SP = f"{VC}/clubs/fa-clube-sp"
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal

    today = date.today()
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        sp = db.scalar(select(m.Sponsor).where(m.Sponsor.email == "marca@superfas.dev"))
        env = {s.key: s for s in artist.ad_slots if s.club_id is None}
        club = next(c for c in artist.clubs if c.slug == "fa-clube-sp")
        cl = {s.key: s for s in artist.ad_slots if s.club_id == club.id}
        assert {"feed_2", "feed_3", "feed_4"} <= set(env) and {"fa-clube-sp.mural", "fa-clube-sp.feed_2", "fa-clube-sp.feed_3"} <= set(cl)
        for slot, title, start, end, status in [
            (env["feed_2"], "Feed8 no ar", today - timedelta(days=1), today + timedelta(days=5), "approved"),
            (env["feed_3"], "Feed12 agendado", today + timedelta(days=3), today + timedelta(days=9), "approved"),
            (env["feed_4"], "Feed16 pendente", today - timedelta(days=1), today + timedelta(days=5), "pending"),
            (cl["fa-clube-sp.mural"], "Clube4 no ar", today - timedelta(days=1), today + timedelta(days=5), "approved"),
            (cl["fa-clube-sp.feed_3"], "Clube12 encerrado", today - timedelta(days=9), today - timedelta(days=2), "approved"),
        ]:
            db.add(m.Campaign(sponsor_id=sp.id, slot_id=slot.id, brand="Marca Feed", title=title, text="t", cta="Ver", url="https://x.com",
                              art_path="/ads/x.png", start=start, end=end, status=status))
        db.commit()

    env_ads = {a["title"]: a for a in client.get(f"{VC}/ads/feed", headers=fan).json() if a["sponsor"] == "Marca Feed"}
    assert set(env_ads) == {"Feed8 no ar"}
    ad = env_ads["Feed8 no ar"]
    assert ad["position"] == 8 and ad["cta"] == "Ver" and ad["url"] == "https://x.com" and ad["artUrl"] == "/ads/x.png"

    club_ads = {a["title"]: a for a in client.get(f"{SP}/ads/feed", headers=fan).json() if a["sponsor"] == "Marca Feed"}
    assert set(club_ads) == {"Clube4 no ar"} and club_ads["Clube4 no ar"]["position"] == 4
    # as rotas vizinhas continuam respondendo
    assert client.get(f"{VC}/ads/home", headers=fan).status_code == 200
    assert client.get(f"{VC}/ads/in-app", headers=fan).status_code == 200
    assert client.get(f"{SP}/ads/home", headers=fan).status_code == 200


def test_ranking_do_fa_traz_o_id_de_cada_pessoa(client, fan):
    rk = client.get("/artists/vintage-culture/ranking", headers=fan).json()
    assert all(r["userId"] for r in rk["top"])
    assert all(r["userId"] for c in rk["clubs"] for r in c["top"])


def test_cada_fa_conta_no_ranking_de_um_clube_so(client, fan):
    rk = client.get("/artists/vintage-culture/ranking", headers=fan).json()
    ids = [r["userId"] for c in rk["clubs"] for r in c["top"]]
    assert len(ids) == len(set(ids))  # ninguém aparece no ranking de dois fã clubes


def test_caronas_por_show_com_valor_retido(client, club_admin, fan):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app import models as m
    from app.carpool.models import Ride
    from app.db import SessionLocal

    base = "/artists/vintage-culture"
    show = (datetime.now(timezone.utc) + timedelta(days=10)).date()
    ev = client.post(f"{base}/manage/events", headers=club_admin, json={"date": show.isoformat(), "city": "Goiânia"}).json()
    motorista = fan  # fa@superfas.dev
    # o passageiro é outra conta: o admin do clube (também é usuário do ambiente)
    passageiro = club_admin
    url = f"{base}/carpool/events/{ev['id']}/rides"
    depart = (datetime.now(timezone.utc) + timedelta(days=5)).replace(microsecond=0).isoformat()

    # validações da oferta
    ruim = {"originCity": "Anápolis", "departAt": depart, "seats": 0, "priceCents": 5000}
    assert client.post(url, headers=motorista, json=ruim).status_code == 422
    passado = {"originCity": "Anápolis", "meetingPoint": "Rua 1, 100, Anápolis - GO", "departAt": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "seats": 3, "priceCents": 5000}
    assert client.post(url, headers=motorista, json=passado).status_code == 400
    r = client.post(url, headers=motorista, json={"originCity": "Anápolis", "meetingPoint": "Posto Shell", "departAt": depart, "seats": 3, "priceCents": 5000, "car": "Gol branco"})
    assert r.status_code == 201, r.text
    ride = r.json()
    assert ride["seatsLeft"] == 3 and ride["mine"] is True and ride["driver"]["name"]

    # reserva: não na própria viagem, não mais vagas do que há
    book = f"{base}/carpool/rides/{ride['id']}/bookings"
    assert client.post(book, headers=motorista, json={"seats": 1}).status_code == 400
    b = client.post(book, headers=passageiro, json={"seats": 2})  # sempre uma vaga por reserva
    assert b.status_code == 201 and b.json()["status"] == "reserved" and b.json()["amountCents"] == 5000 and b.json()["seats"] == 1
    visto = client.get(url, headers=passageiro).json()[0]
    assert visto["seatsLeft"] == 2 and visto["myBooking"]["status"] == "reserved" and visto["passengers"] == []
    assert client.post(book, headers=passageiro, json={"seats": 1}).status_code == 400  # uma reserva por show

    # pagamento: o valor fica retido; dá para devolver (faltam mais de 24 h)
    pay = f"{base}/carpool/bookings/{b.json()['id']}/pay"
    assert client.post(pay, headers=passageiro).json()["status"] == "paid"
    assert client.post(pay, headers=passageiro).status_code == 400
    adm = client.get(f"{base}/manage/carpool", headers=club_admin).json()
    assert adm["heldCents"] >= 5000 and any(i["ride"]["id"] == ride["id"] for i in adm["items"])
    assert client.get(f"{base}/carpool/me", headers=motorista).json()["offered"][0]["passengers"][0]["status"] == "paid"
    cancel = client.post(f"{base}/carpool/bookings/{b.json()['id']}/cancel", headers=passageiro)
    assert cancel.status_code == 200 and cancel.json()["status"] == "refunded"
    assert client.get(url, headers=passageiro).json()[0]["seatsLeft"] == 3  # as vagas voltaram

    # nova reserva, paga; só confirma depois da saída; confirma e libera ao motorista
    b2 = client.post(book, headers=passageiro, json={"seats": 1}).json()
    client.post(f"{base}/carpool/bookings/{b2['id']}/pay", headers=passageiro)
    assert client.post(f"{base}/carpool/bookings/{b2['id']}/confirm", headers=passageiro).status_code == 400  # ainda não saiu
    with SessionLocal() as db:
        rd = db.scalar(select(Ride).where(Ride.id == ride["id"]))
        rd.depart_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()
    done = client.post(f"{base}/carpool/bookings/{b2['id']}/confirm", headers=passageiro)
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert client.get(f"{base}/manage/carpool", headers=fan).status_code == 403  # só a administração
    assert client.get(f"{base}/carpool/events/nao-existe/rides", headers=fan).status_code == 404

    # o motorista cancela uma viagem com passageiro pago: devolve o valor
    r2 = client.post(url, headers=motorista, json={"originCity": "Trindade", "departAt": depart, "meetingPoint": "Rua 1, 100, Trindade - GO", "seats": 2, "priceCents": 3000}).json()
    b3 = client.post(f"{base}/carpool/rides/{r2['id']}/bookings", headers=passageiro, json={"seats": 1}).json()
    client.post(f"{base}/carpool/bookings/{b3['id']}/pay", headers=passageiro)
    assert client.post(f"{base}/carpool/rides/{r2['id']}/cancel", headers=passageiro).status_code == 404  # só o motorista
    assert client.post(f"{base}/carpool/rides/{r2['id']}/cancel", headers=motorista).json()["status"] == "cancelled"
    assert any(x["status"] == "refunded" for x in client.get(f"{base}/carpool/me", headers=passageiro).json()["booked"])
