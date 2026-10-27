"""Correções da revenda achadas no QA: para onde transferir, endereço, dono de fã clube, teto na reaprovação,
saldo do anúncio aberto, cancelamento de reserva vencida e anúncios do vendedor depois do show."""

from datetime import datetime, timezone

from tests.test_resale import ADM, ART, R, advance, as_seller, new_listing, real_clock, register, resale_on, reserve, world  # noqa: F401


def test_comprador_informa_para_onde_transferir_e_vendedor_so_ve_depois_de_pagar(client, world, club_admin):
    vend = as_seller(client, "destvend")
    li = new_listing(client, world, vend, qty=2, approve_with=club_admin)
    comp = register(client, "destcomp")

    ruim = client.post(f"{R}/listings/{li['id']}/orders", headers=comp, json={"qty": 1, "transferTo": "sem-arroba"})
    assert ruim.status_code == 400 and ruim.json()["code"] == "TRANSFER_TO_INVALID"

    o = client.post(f"{R}/listings/{li['id']}/orders", headers=comp, json={"qty": 1, "transferTo": "Minha.Conta@Ticket.dev"}).json()
    assert o["transferTo"] == "minha.conta@ticket.dev" and o["createdAt"]
    antes = client.get(f"{R}/orders/{o['id']}", headers=vend).json()
    assert antes["role"] == "seller" and antes["transferTo"] is None  # reservado: o vendedor ainda não vê

    assert client.post(f"{R}/orders/{o['id']}/pay", headers=comp).json()["status"] == "awaiting_transfer"
    depois = client.get(f"{R}/orders/{o['id']}", headers=vend).json()
    assert depois["transferTo"] == "minha.conta@ticket.dev" and depois["canMarkTransferred"] is True


def test_sem_transfer_to_usa_o_email_do_cadastro(client, world, club_admin):
    vend = as_seller(client, "defvend")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    comp = register(client, "defcomp")
    email = client.get("/auth/profile", headers=comp).json()["email"]
    o = reserve(client, comp, li["id"]).json()
    assert o["transferTo"] == email.lower()


def test_endereco_completa_o_cadastro_para_comprar(client, world):
    sem = register(client, "endereco", complete=False)
    assert "address" in client.get(f"{R}/me/eligibility", headers=sem).json()["missing"]
    assert client.put("/auth/address", headers=sem, json={"zipCode": "123", "street": "Rua A", "number": "1", "neighborhood": "Centro", "city": "Campinas", "state": "SP"}).status_code == 422
    r = client.put("/auth/address", headers=sem, json={"zipCode": "13000000", "street": "Rua A", "number": "1", "neighborhood": "Centro", "city": "Campinas", "state": "sp"})
    assert r.status_code == 200 and r.json()["zipCode"] == "13000-000" and r.json()["state"] == "SP"
    e = client.get(f"{R}/me/eligibility", headers=sem).json()
    assert e["canBuy"] is True and "address" not in e["missing"]


def test_dono_de_fa_clube_entra_na_revenda_sem_fandom(client, world, club_admin):
    assert "fandom" not in client.get(f"{R}/me/eligibility", headers=club_admin).json()["missing"]


def test_reaprovar_anuncio_pausado_confere_o_teto(client, club_admin):
    ev = client.post(f"{ART}/manage/events", headers=club_admin, json={"date": "2031-10-10", "city": "Teto City", "venue": "Arena", "time": "22h"}).json()
    t = client.post(f"{ART}/manage/tickets", headers=club_admin, json={"eventId": ev["id"], "label": "Pista", "priceCents": 20000}).json()
    assert client.put(f"{ADM}/events/{ev['id']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": True}).status_code == 200
    vend = as_seller(client, "tetovend")
    li = new_listing(client, {"event": ev["id"], "ticket": t["id"]}, vend, qty=1, price=19000)
    assert client.patch(f"{ART}/manage/tickets/{t['id']}", headers=club_admin, json={"priceCents": 15000}).status_code == 200
    r = client.post(f"{ADM}/listings/{li['id']}/approve", headers=club_admin)
    assert r.status_code == 409 and r.json()["code"] == "PRICE_ABOVE_FACE"


def test_anuncio_aberto_devolve_saldo_de_reserva_vencida(client, world, club_admin):
    vend = as_seller(client, "saldovend")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    comp = register(client, "saldocomp")
    assert reserve(client, comp, li["id"]).status_code == 201
    assert client.get(f"{R}/listings/{li['id']}", headers=comp).json()["qtyAvailable"] == 0
    advance(minutes=16)
    assert client.get(f"{R}/listings/{li['id']}", headers=comp).json()["qtyAvailable"] == 1


def test_cancelar_reserva_vencida_fica_expirada(client, world, club_admin):
    vend = as_seller(client, "expvend")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    comp = register(client, "expcomp")
    o = reserve(client, comp, li["id"]).json()
    advance(minutes=16)
    r = client.post(f"{R}/orders/{o['id']}/cancel", headers=comp)
    assert r.status_code == 409 or (r.json()["status"] == "expired" and r.json()["closeReason"] == "reservation_expired"), r.text
    o2 = client.get(f"{R}/orders/{o['id']}", headers=comp).json()
    assert o2["status"] == "expired" and o2["closeReason"] == "reservation_expired"


def test_meus_anuncios_fecham_depois_do_show(client, world, club_admin):
    vend = as_seller(client, "showvend")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    now = datetime.now(timezone.utc)
    advance(seconds=(datetime(2031, 9, 13, 6, tzinfo=timezone.utc) - now).total_seconds())
    mine = {x["id"]: x for x in client.get(f"{R}/me/listings", headers=vend).json()}
    assert mine[li["id"]]["status"] == "closed" and mine[li["id"]]["canCancel"] is False


def test_avaliacao_devolve_data_e_nota_invalida_e_400(client, world, club_admin):
    vend = as_seller(client, "avvend")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    comp = register(client, "avcomp")
    o = reserve(client, comp, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    client.post(f"{R}/orders/{o['id']}/transferred", headers=vend)
    client.post(f"{R}/orders/{o['id']}/confirm", headers=comp)
    bad = client.post(f"{R}/orders/{o['id']}/review", headers=comp, json={"rating": 9})
    assert bad.status_code == 400 and bad.json()["code"] == "RATING_INVALID"
    ok = client.post(f"{R}/orders/{o['id']}/review", headers=comp, json={"rating": 5, "comment": "Tudo certo"})
    assert ok.status_code == 201 and ok.json()["createdAt"]


def test_comprador_ve_whatsapp_do_vendedor_so_depois_de_pagar(client, world, club_admin):
    vend = as_seller(client, "zapvend")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    comp = register(client, "zapcomp")
    o = reserve(client, comp, li["id"]).json()
    assert o["sellerPhone"] is None  # reservado: ainda não pagou
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    assert client.get(f"{R}/orders/{o['id']}", headers=comp).json()["sellerPhone"] == "19999991234"
    assert client.get(f"{R}/orders/{o['id']}", headers=vend).json()["sellerPhone"] is None
    adm = [x for x in client.get(f"{ADM}/orders", headers=club_admin).json() if x["id"] == o["id"]]
    assert adm and adm[0]["sellerPhone"] is None
