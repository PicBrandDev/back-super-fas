"""Revenda de ingressos: identidade, liberação do show, anúncios com prova, escrow (reserva, pagamento, transferência,
confirmação, disputa), prazos, taxa, privacidade e concorrência."""

import itertools
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.resale import base as rb
from app.resale.identity import clean_phone, valid_cpf, valid_phone
from tests.conftest import PASSWORD, login

ART = "/artists/vintage-culture"
R = f"{ART}/resale"
ADM = f"{R}/admin"
PNG = bytes([137]) + b"PNG" + bytes([13, 10, 26, 10])
_n = itertools.count(1)


def make_cpf(seed: int) -> str:
    """CPF válido a partir de um número (calcula os dois dígitos verificadores)."""
    d = [int(c) for c in f"{seed:09d}"[-9:]]
    if len(set(d)) == 1:
        d[0] = (d[0] + 1) % 10
    for size in (9, 10):
        total = sum(d[i] * (size + 1 - i) for i in range(size))
        d.append((total * 10 % 11) % 10)
    return "".join(map(str, d))


def proof(tag: str = "") -> dict:
    return {"proof": (f"p{next(_n)}.png", PNG + f"{tag}{uuid.uuid4()}".encode(), "image/png")}


@pytest.fixture(autouse=True)
def real_clock():
    yield
    rb.set_clock(None)


def advance(**delta):
    base = datetime.now(timezone.utc)
    rb.set_clock(lambda: base + timedelta(**delta))


def register(client, tag: str, complete: bool = True, club: bool = True) -> dict:
    email = f"resale-{tag}-{uuid.uuid4().hex[:6]}@teste.dev"
    body = {"name": f"Fã {tag.title()} Silva", "email": email, "password": PASSWORD, "handle": f"@{tag}{next(_n)}", "city": "Campinas", "artist": "vintage-culture" if club else None}
    if complete:
        body.update(zipCode="13000-000", street="Rua das Flores", number="100", neighborhood="Centro", state="SP")
    assert client.post("/auth/register", json=body).status_code == 201
    return login(client, email)


def as_seller(client, tag: str = "seller") -> dict:
    h = register(client, tag)
    r = client.put("/me/identity", headers=h, json={"cpf": make_cpf(next(_n) * 7919 + 100000), "phone": "(19) 99999-1234"})
    assert r.status_code == 200, r.text
    return h


@pytest.fixture(scope="module")
def world(client, club_admin):
    """Um show futuro (22h) com ingresso Pista de R$ 200, ticketeira esgotada e revenda liberada pelo admin."""
    ev = client.post(f"{ART}/manage/events", headers=club_admin, json={"date": "2031-09-12", "city": "Revenda City", "venue": "Arena", "time": "22h"}).json()
    t = client.post(f"{ART}/manage/tickets", headers=club_admin, json={"eventId": ev["id"], "label": "Pista", "priceCents": 20000}).json()
    r = client.put(f"{ADM}/events/{ev['id']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": True})
    assert r.status_code == 200 and r.json()["isOpen"] is True, r.text
    return {"event": ev["id"], "ticket": t["id"]}


def new_listing(client, world, seller, qty=3, price=18000, approve_with=None, codes=None):
    codes = codes or [f"TK{uuid.uuid4().hex[:8].upper()}" for _ in range(qty)]
    r = client.post(f"{R}/events/{world['event']}/listings", headers=seller, data={"ticketId": world["ticket"], "qty": qty, "unitPriceCents": price, "codes": codes}, files=proof())
    assert r.status_code == 201, r.text
    li = r.json()
    if approve_with:
        a = client.post(f"{ADM}/listings/{li['id']}/approve", headers=approve_with)
        assert a.status_code == 200, a.text
    return li


def reserve(client, buyer, listing_id, qty=1, key=None):
    h = dict(buyer)
    if key:
        h["Idempotency-Key"] = key
    return client.post(f"{R}/listings/{listing_id}/orders", headers=h, json={"qty": qty})


def ledger(client, club_admin, order_id):
    return {e["kind"]: e for e in client.get(f"{ADM}/ledger?orderId={order_id}", headers=club_admin).json()}


# ---------------------------------------------------------------- unitários


def test_cpf_telefone_taxa_e_horario():
    assert valid_cpf("52998224725") and not valid_cpf("52998224726") and not valid_cpf("11111111111") and not valid_cpf("123")
    assert clean_phone("+55 (19) 99999-1234") == "19999991234" and valid_phone("19999991234") and not valid_phone("123")
    assert rb.split_fee(10000, 0) == (0, 10000)
    assert rb.split_fee(10000, 1500) == (1500, 8500)
    assert rb.split_fee(333, 1500) == (50, 283)  # 49,95 arredonda para 50 (half-up)
    for gross in (1, 99, 12345, 55555):
        for bps in (0, 150, 1500, 3000):
            fee, net = rb.split_fee(gross, bps)
            assert fee + net == gross and net >= 0
    assert rb.parse_show_time("22h") == (22, 0) and rb.parse_show_time("21h30") == (21, 30) and rb.parse_show_time("às 20:15") == (20, 15)
    assert rb.parse_show_time("noite") is None and rb.parse_show_time("25h") is None


# ---------------------------------------------------------------- identidade e elegibilidade


def test_identidade_mascarada_unica_e_sem_vazamento(client):
    a, b = register(client, "ident"), register(client, "ident2")
    assert client.put("/me/identity", headers=a, json={"cpf": "11111111111", "phone": "19999991234"}).status_code == 400
    assert client.put("/me/identity", headers=a, json={"cpf": make_cpf(123456789), "phone": "123456789012"}).json()["code"] == "INVALID_PHONE"
    cpf = make_cpf(222333444)
    ok = client.put("/me/identity", headers=a, json={"cpf": cpf, "phone": "(19) 99999-1234"}).json()
    assert ok["cpfMasked"] == f"***.***.***-{cpf[-2:]}" and ok["phoneMasked"] == "(**) *****-1234" and ok["level"] == "declared"
    assert cpf not in json.dumps(ok) and "99999" not in json.dumps(ok)
    assert client.put("/me/identity", headers=b, json={"cpf": cpf, "phone": "19999991234"}).json()["code"] == "CPF_IN_USE"
    assert client.put("/me/identity", headers=a, json={"cpf": make_cpf(999888777), "phone": "19999991234"}).json()["code"] == "CPF_LOCKED"
    assert client.put("/me/identity", headers=a, json={"cpf": cpf, "phone": "19988887777"}).status_code == 200  # só o telefone muda
    assert client.post("/me/identity/verify/email/start", headers=a).status_code == 501  # ponto de extensão do MFA


def test_elegibilidade(client, world):
    sem_endereco = register(client, "semend", complete=False)
    assert client.get(f"{R}/me/eligibility", headers=sem_endereco).json() == {"canBuy": False, "canSell": False, "missing": ["address", "cpf", "phone"]}
    sem_clube = register(client, "semclube", club=False)
    assert "fandom" in client.get(f"{R}/me/eligibility", headers=sem_clube).json()["missing"]
    comprador = register(client, "comp")
    e = client.get(f"{R}/me/eligibility", headers=comprador).json()
    assert e["canBuy"] and not e["canSell"] and e["missing"] == ["cpf", "phone"]
    assert client.get(f"{R}/me/eligibility", headers=as_seller(client, "vend")).json()["canSell"] is True
    # quem não tem identidade não vende
    r = client.post(f"{R}/events/{world['event']}/listings", headers=comprador, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["ABCD1234"]}, files=proof())
    assert r.status_code == 403 and r.json()["code"] == "NOT_ELIGIBLE"


def test_patrocinador_e_master_nao_vendem(client, sponsor, master, world):
    assert client.get(f"{R}/me/eligibility", headers=sponsor).json()["canSell"] is False
    assert client.get(f"{R}/me/eligibility", headers=master).json()["canBuy"] is False


# ---------------------------------------------------------------- liberação do show (chaves do admin)


def test_show_so_aparece_com_as_duas_chaves_e_horario_legivel(client, club_admin, fan, world):
    ev = client.post(f"{ART}/manage/events", headers=club_admin, json={"date": "2031-10-10", "city": "Chaves", "time": "22h"}).json()
    ids = lambda: [e["id"] for e in client.get(f"{R}/events", headers=fan).json()]  # noqa: E731
    assert world["event"] in ids() and ev["id"] not in ids()
    assert client.get(f"{R}/events/{ev['id']}", headers=fan).json()["code"] == "RESALE_CLOSED"
    # abrir sem marcar esgotado, ou sem horário legível, ou show passado, é recusado
    assert client.put(f"{ADM}/events/{ev['id']}", headers=club_admin, json={"ticketingSoldOut": False, "resaleOpen": True}).json()["code"] == "NOT_SOLD_OUT"
    sem_hora = client.post(f"{ART}/manage/events", headers=club_admin, json={"date": "2031-10-11", "city": "Sem hora", "time": "à noite"}).json()
    assert client.put(f"{ADM}/events/{sem_hora['id']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": True}).json()["code"] == "TIME_UNREADABLE"
    passado = client.post(f"{ART}/manage/events", headers=club_admin, json={"date": "2020-01-01", "city": "Passado", "time": "22h"}).json()
    assert client.put(f"{ADM}/events/{passado['id']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": True}).json()["code"] == "EVENT_PAST"
    assert client.put(f"{ADM}/events/{ev['id']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": True}).status_code == 200
    assert ev["id"] in ids()
    # só o admin do ambiente liga as chaves
    assert client.put(f"{ADM}/events/{ev['id']}", headers=fan, json={"ticketingSoldOut": True, "resaleOpen": True}).status_code == 403
    client.put(f"{ADM}/events/{ev['id']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": False})
    assert ev["id"] not in ids()


# ---------------------------------------------------------------- anúncios


def test_regras_do_anuncio_e_prova(client, club_admin, fan, world):
    s = as_seller(client)
    url = f"{R}/events/{world['event']}/listings"

    def post(**over):
        data = {"ticketId": world["ticket"], "qty": 2, "unitPriceCents": 19000, "codes": ["AAAA1111", "BBBB2222"], **over}
        files = over.pop("files", None) or proof()
        data.pop("files", None)
        return client.post(url, headers=s, data=data, files=files)

    assert post(unitPriceCents=20001).json()["code"] == "PRICE_ABOVE_FACE"  # teto = valor de face
    assert post(unitPriceCents=0).status_code == 400
    assert post(codes=["AAAA1111"]).json()["code"] == "CODES_COUNT"
    assert post(codes=["AAAA1111", "AAAA1111"]).json()["code"] == "CODES_REPEATED"
    assert post(codes=["AB", "CD"]).json()["code"] == "CODE_INVALID"
    assert client.post(url, headers=s, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["ABCD1234"]}).json()["code"] == "PROOF_REQUIRED"
    texto = client.post(url, headers=s, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["ABCD1234"]}, files={"proof": ("x.png", b"isto nao e imagem", "image/png")})
    assert texto.json()["code"] == "PROOF_TYPE"  # valida o conteúdo, não o Content-Type
    assert client.post(url, headers=s, data={"ticketId": "nao-existe", "qty": 1, "unitPriceCents": 100, "codes": ["ABCD1234"]}, files=proof()).status_code == 404

    ok = post(codes=["ZZZZ0001", "ZZZZ0002"])
    assert ok.status_code == 201 and ok.json()["status"] == "pending_review" and ok.json()["canCancel"] is True
    # o mesmo ingresso não pode ser anunciado duas vezes (nem em outra conta)
    outro = as_seller(client, "outro")
    dup = client.post(url, headers=outro, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["zzzz 0001"]}, files=proof())
    assert dup.status_code == 409 and dup.json()["code"] == "CODE_DUPLICATE"
    # nem o mesmo arquivo de prova
    arq = PNG + b"mesmo-arquivo"
    assert client.post(url, headers=outro, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["QQQQ0001"]}, files={"proof": ("a.png", arq, "image/png")}).status_code == 201
    assert client.post(url, headers=outro, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["QQQQ0002"]}, files={"proof": ("b.png", arq, "image/png")}).json()["code"] == "PROOF_DUPLICATE"
    # rejeitar exige motivo, e os códigos voltam a poder ser anunciados
    lid = ok.json()["id"]
    assert client.post(f"{ADM}/listings/{lid}/reject", headers=club_admin, json={"reason": " "}).status_code in (400, 422)
    rej = client.post(f"{ADM}/listings/{lid}/reject", headers=club_admin, json={"reason": "Foto ilegível"}).json()
    assert rej["status"] == "rejected" and rej["reviewReason"] == "Foto ilegível"
    assert client.post(url, headers=outro, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["ZZZZ0001"]}, files=proof()).status_code == 201
    # reenvio do vendedor
    res = client.post(f"{R}/listings/{lid}/resubmit", headers=s, data={"codes": ["YYYY0001", "YYYY0002"]}, files=proof())
    assert res.status_code == 200 and res.json()["status"] == "pending_review" and res.json()["attempts"] == 2
    # só o dono mexe no anúncio
    assert client.post(f"{R}/listings/{lid}/cancel", headers=outro).status_code == 403


def test_anuncio_so_aparece_depois_da_aprovacao_com_confianca_do_vendedor(client, club_admin, world):
    s = as_seller(client, "conf")
    comprador = register(client, "ver")
    li = new_listing(client, world, s, qty=2)
    page = client.get(f"{R}/events/{world['event']}/listings", headers=comprador).json()
    assert li["id"] not in [i["id"] for i in page["items"]]
    assert client.get(f"{R}/listings/{li['id']}", headers=comprador).status_code == 404
    admin_view = client.get(f"{ADM}/listings/{li['id']}", headers=club_admin).json()
    assert len(admin_view["codes"]) == 2 and admin_view["verifierStatus"] == "unknown" and admin_view["proofUrl"].endswith("/proof")
    client.post(f"{ADM}/listings/{li['id']}/approve", headers=club_admin)
    item = next(i for i in client.get(f"{R}/events/{world['event']}/listings", headers=comprador).json()["items"] if i["id"] == li["id"])
    sel = item["seller"]
    assert sel["completedSales"] == 0 and sel["ratingCount"] == 0 and sel["memberSince"] and sel["identityLevel"] == "declared" and sel["identityVerified"] is False
    assert sel["handle"].startswith("@conf") and sel["displayName"].endswith("S.") and any(c["position"] == "member" for c in sel["clubs"])
    detail = client.get(f"{R}/events/{world['event']}", headers=comprador).json()
    assert detail["ticketTypes"][0]["faceCents"] == 20000


def test_prova_so_para_o_admin_e_fora_do_uploads_publico(client, club_admin, fan, world):
    s = as_seller(client, "prova")
    li = new_listing(client, world, s)
    ok = client.get(f"{ADM}/listings/{li['id']}/proof", headers=club_admin)
    assert ok.status_code == 200 and ok.content.startswith(PNG) and ok.headers["x-content-type-options"] == "nosniff" and "attachment" in ok.headers["content-disposition"]
    assert client.get(f"{ADM}/listings/{li['id']}/proof", headers=fan).status_code == 403
    assert client.get(f"{ADM}/listings/{li['id']}/proof", headers=s).status_code == 403
    assert client.get(f"{ADM}/listings/{li['id']}/proof").status_code == 401


# ---------------------------------------------------------------- fluxo completo com escrow e taxa


def test_fluxo_completo_com_taxa_e_livro_razao(client, club_admin, world):
    client.put(f"{ADM}/settings", headers=club_admin, json={"feeBps": 1500})
    vend, comp = as_seller(client, "fluxo"), register(client, "compfluxo")
    li = new_listing(client, world, vend, qty=3, price=18000, approve_with=club_admin)
    o = reserve(client, comp, li["id"], qty=2, key="chave-fluxo-0001")  # compra parcial: 2 de 3
    assert o.status_code == 201, o.text
    o = o.json()
    assert o["status"] == "reserved" and o["grossCents"] == 36000 and o["feeCents"] == 5400 and o["sellerNetCents"] == 30600 and o["canPay"] is True
    assert o["counterparty"]["handle"].startswith("@fluxo") and o["buyerHandle"] is None  # comprador vê o vendedor; não o contrário
    assert client.get(f"{R}/events/{world['event']}/listings", headers=comp).json()["items"][0]["qtyAvailable"] in (1, 2, 3)
    # a taxa muda, mas o pedido já criado guarda a antiga
    client.put(f"{ADM}/settings", headers=club_admin, json={"feeBps": 0})
    # só o comprador paga; o vendedor ainda não pode transferir antes do pagamento
    assert client.post(f"{R}/orders/{o['id']}/pay", headers=vend).status_code == 403  # o vendedor participa do pedido, mas não é o comprador
    assert client.post(f"{R}/orders/{o['id']}/transferred", headers=vend).status_code == 409
    paid = client.post(f"{R}/orders/{o['id']}/pay", headers=comp).json()
    assert paid["status"] == "awaiting_transfer" and paid["transferDeadline"] and paid["feeCents"] == 5400
    assert client.post(f"{R}/orders/{o['id']}/pay", headers=comp).json()["status"] == "awaiting_transfer"  # repetir é idempotente
    led = ledger(client, club_admin, o["id"])
    assert led["hold"]["amountCents"] == 36000 and led["hold"]["debitAccount"] == "buyer_external" and led["hold"]["status"] == "settled"
    # o valor continua retido até a confirmação
    assert "release_seller" not in led
    # o vendedor vê o pedido sem dados do comprador além do handle
    sv = client.get(f"{R}/orders/{o['id']}", headers=vend).json()
    assert sv["role"] == "seller" and sv["canMarkTransferred"] is True and sv["counterparty"] is None and sv["buyerHandle"].startswith("@compfluxo")
    tr = client.post(f"{R}/orders/{o['id']}/transferred", headers=vend).json()
    assert tr["status"] == "transferred" and tr["confirmDeadline"]
    assert client.post(f"{R}/orders/{o['id']}/confirm", headers=vend).status_code == 403
    done = client.post(f"{R}/orders/{o['id']}/confirm", headers=comp).json()
    assert done["status"] == "completed" and done["canReview"] is True
    assert client.post(f"{R}/orders/{o['id']}/confirm", headers=comp).json()["status"] == "completed"  # idempotente
    led = ledger(client, club_admin, o["id"])
    assert led["release_seller"]["amountCents"] == 30600 and led["fee"]["amountCents"] == 5400 and "refund" not in led
    assert led["hold"]["amountCents"] == led["release_seller"]["amountCents"] + led["fee"]["amountCents"]  # o escrow zera
    # avaliação (uma vez, 1 a 5) e confiança do vendedor
    assert client.post(f"{R}/orders/{o['id']}/review", headers=comp, json={"rating": 6}).status_code == 422
    assert client.post(f"{R}/orders/{o['id']}/review", headers=comp, json={"rating": 5, "comment": "Tudo certo!"}).status_code == 201
    assert client.post(f"{R}/orders/{o['id']}/review", headers=comp, json={"rating": 4}).json()["code"] == "ALREADY_REVIEWED"
    seller_id = o["counterparty"]["userId"]
    prof = client.get(f"{R}/sellers/{seller_id}", headers=comp).json()
    assert prof["completedSales"] == 1 and prof["avgRating"] == 5.0 and prof["ratingCount"] == 1
    revs = client.get(f"{R}/sellers/{seller_id}/reviews", headers=comp).json()
    assert revs[0]["comment"] == "Tudo certo!" and revs[0]["buyerName"].endswith("S.")


def test_privacidade_nenhuma_resposta_publica_traz_cpf_telefone_ou_email(client, club_admin, world):
    vend = register(client, "priv")
    cpf = make_cpf(777666555)
    client.put("/me/identity", headers=vend, json={"cpf": cpf, "phone": "(19) 98877-6655"})
    me = client.get("/auth/me", headers=vend).json()
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    comp = register(client, "privcomp")
    o = reserve(client, comp, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    dumps = [
        client.get(f"{R}/events/{world['event']}/listings", headers=comp).text,
        client.get(f"{R}/listings/{li['id']}", headers=comp).text,
        client.get(f"{R}/sellers/{o['counterparty']['userId']}", headers=comp).text,
        client.get(f"{R}/orders/{o['id']}", headers=comp).text,
        client.get(f"{R}/orders/{o['id']}", headers=vend).text,
        client.get(f"{R}/me/orders", headers=comp).text,
        client.get(f"{ADM}/listings/{li['id']}", headers=club_admin).text,
        client.get(f"{ADM}/orders", headers=club_admin).text,
        client.get("/me/identity", headers=vend).text,
    ]
    for text in dumps:
        assert cpf not in text and "98877" not in text and me["email"] not in text and not any(c in text for c in ("cpfEnc", "cpf_enc", "cpfHash"))
        assert "resale-priv-" not in text  # o prefixo do e-mail nunca vira nome público


# ---------------------------------------------------------------- reserva, saldo e prazos


def test_reserva_expira_devolve_saldo_uma_vez_e_pagamento_tardio_e_recusado(client, club_admin, world):
    vend, comp = as_seller(client, "exp"), register(client, "compexp")
    li = new_listing(client, world, vend, qty=2, approve_with=club_admin)
    o = reserve(client, comp, li["id"], qty=2).json()
    me_li = lambda: next(x for x in client.get(f"{R}/me/listings", headers=vend).json() if x["id"] == li["id"])  # noqa: E731
    assert me_li()["qtyAvailable"] == 0
    advance(minutes=16)
    for _ in range(3):  # várias varreduras seguidas não devolvem o saldo em dobro
        assert client.get(f"{R}/me/orders", headers=comp).json()[0]["status"] == "expired"
    assert me_li()["qtyAvailable"] == 2
    late = client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    assert late.status_code == 409 and late.json()["code"] == "RESERVATION_EXPIRED"
    assert ledger(client, club_admin, o["id"]) == {}  # nada foi cobrado


def test_cancelar_reserva_devolve_saldo(client, club_admin, world):
    vend, comp = as_seller(client, "can"), register(client, "compcan")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    assert client.post(f"{R}/orders/{o['id']}/cancel", headers=comp).json()["status"] == "cancelled"
    assert client.post(f"{R}/orders/{o['id']}/cancel", headers=comp).json()["status"] == "cancelled"
    assert next(x for x in client.get(f"{R}/me/listings", headers=vend).json() if x["id"] == li["id"])["qtyAvailable"] == 1


def test_nao_vende_em_dobro_e_respeita_limites(client, club_admin, world):
    vend = as_seller(client, "dobro")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    a, b = register(client, "da"), register(client, "db")
    assert reserve(client, a, li["id"]).status_code == 201
    segunda = reserve(client, b, li["id"])
    assert segunda.status_code == 409 and segunda.json()["code"] == "QTY_UNAVAILABLE"
    # não reserva o mesmo anúncio duas vezes, nem o próprio anúncio
    li2 = new_listing(client, world, vend, qty=3, approve_with=club_admin)
    assert reserve(client, a, li2["id"]).status_code == 201
    assert reserve(client, a, li2["id"]).json()["code"] == "ALREADY_RESERVED"
    assert reserve(client, vend, li2["id"]).json()["code"] == "OWN_LISTING"
    assert reserve(client, b, li2["id"], qty=4).status_code == 400  # mais que o lote
    assert reserve(client, b, li2["id"], qty=0).status_code == 422


def test_concorrencia_so_uma_reserva_leva_o_ultimo_ingresso(client, club_admin, world):
    vend = as_seller(client, "conc")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    buyers = [register(client, f"cc{i}") for i in range(4)]
    results, gate = [], threading.Barrier(len(buyers))

    def go(h):
        with TestClient(app) as c:
            gate.wait()
            results.append(reserve(c, h, li["id"]).status_code)

    threads = [threading.Thread(target=go, args=(h,)) for h in buyers]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [201, 409, 409, 409]
    assert next(x for x in client.get(f"{R}/me/listings", headers=vend).json() if x["id"] == li["id"])["qtyAvailable"] == 0


def test_idempotencia_da_reserva(client, club_admin, world):
    vend, comp = as_seller(client, "idem"), register(client, "compidem")
    li = new_listing(client, world, vend, qty=3, approve_with=club_admin)
    a = reserve(client, comp, li["id"], qty=1, key="minha-chave-0001")
    b = reserve(client, comp, li["id"], qty=1, key="minha-chave-0001")
    assert a.status_code == 201 and b.json()["id"] == a.json()["id"]
    assert reserve(client, comp, li["id"], qty=2, key="minha-chave-0001").json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert reserve(client, comp, li["id"], qty=1, key="curta").json()["code"] == "IDEMPOTENCY_KEY"
    assert next(x for x in client.get(f"{R}/me/listings", headers=vend).json() if x["id"] == li["id"])["qtyAvailable"] == 2  # só uma reserva contou


def test_compra_bloqueada_a_menos_de_4h_do_show_e_com_a_chave_fechada(client, club_admin, world):
    vend, comp = as_seller(client, "tempo"), register(client, "comptempo")
    li = new_listing(client, world, vend, qty=2, approve_with=club_admin)
    start = rb.show_start(datetime(2031, 9, 12).date(), "22h")
    base = datetime.now(timezone.utc)
    rb.set_clock(lambda: base + (start - base) - timedelta(hours=3))  # faltam 3h para o show
    assert reserve(client, comp, li["id"]).json()["code"] == "RESALE_CLOSED"
    rb.set_clock(None)
    # admin fecha a chave: some do hub e bloqueia novas reservas; pedido em andamento segue
    o = reserve(client, comp, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    client.put(f"{ADM}/events/{world['event']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": False})
    assert reserve(client, register(client, "tarde"), li["id"]).json()["code"] == "RESALE_CLOSED"
    assert client.get(f"{R}/orders/{o['id']}", headers=vend).json()["status"] == "awaiting_transfer"
    assert client.post(f"{R}/orders/{o['id']}/transferred", headers=vend).json()["status"] == "transferred"
    client.put(f"{ADM}/events/{world['event']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": True})


def test_prazo_de_transferencia_e_o_menor_entre_24h_e_2h_antes_do_show(client, club_admin, world):
    vend, comp = as_seller(client, "prazo"), register(client, "compprazo")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    start = rb.show_start(datetime(2031, 9, 12).date(), "22h")
    base = datetime.now(timezone.utc)
    rb.set_clock(lambda: start - timedelta(hours=10))  # faltam 10h: o prazo de 24h estouraria o show
    o = reserve(client, comp, li["id"]).json()
    paid = client.post(f"{R}/orders/{o['id']}/pay", headers=comp).json()
    assert datetime.fromisoformat(paid["transferDeadline"]) == start - timedelta(hours=2)
    rb.set_clock(None)


def test_vendedor_nao_transfere_reembolsa_sem_devolver_saldo(client, club_admin, world):
    vend, comp = as_seller(client, "sumiu"), register(client, "compsumiu")
    li = new_listing(client, world, vend, qty=2, approve_with=club_admin)
    o = reserve(client, comp, li["id"], qty=1).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    advance(hours=25)
    got = client.get(f"{R}/orders/{o['id']}", headers=comp).json()
    assert got["status"] == "refunded" and got["closeReason"] == "seller_no_transfer"
    led = ledger(client, club_admin, o["id"])
    assert led["refund"]["amountCents"] == led["hold"]["amountCents"] == 18000 and "release_seller" not in led and led["refund"]["status"] == "settled"
    assert client.get(f"{R}/orders/{o['id']}", headers=comp).json()["status"] == "refunded"  # repetir não duplica
    assert len(client.get(f"{ADM}/ledger?orderId={o['id']}", headers=club_admin).json()) == 2
    assert next(x for x in client.get(f"{R}/me/listings", headers=vend).json() if x["id"] == li["id"])["qtyAvailable"] == 1  # o ingresso não voltou


def test_comprador_nao_confirma_libera_ao_vendedor_apos_48h(client, club_admin, world):
    vend, comp = as_seller(client, "auto"), register(client, "compauto")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    client.post(f"{R}/orders/{o['id']}/transferred", headers=vend)
    advance(hours=47)
    assert client.get(f"{R}/orders/{o['id']}", headers=comp).json()["status"] == "transferred"
    advance(hours=49)
    got = client.get(f"{R}/orders/{o['id']}", headers=vend).json()
    assert got["status"] == "completed" and got["closeReason"] == "auto_release"
    led = ledger(client, club_admin, o["id"])
    assert led["release_seller"]["amountCents"] == 18000 and "refund" not in led


# ---------------------------------------------------------------- disputa


def _transferred_order(client, club_admin, world, tag):
    vend, comp = as_seller(client, f"v{tag}"), register(client, f"c{tag}")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    client.post(f"{R}/orders/{o['id']}/transferred", headers=vend)
    return vend, comp, o


def test_disputa_reembolsa_e_congela_a_liberacao_automatica(client, club_admin, fan, world):
    vend, comp, o = _transferred_order(client, club_admin, world, "d1")
    assert client.post(f"{R}/orders/{o['id']}/dispute", headers=vend, json={"reasonCode": "other"}).status_code == 403
    assert client.post(f"{R}/orders/{o['id']}/dispute", headers=comp, json={"reasonCode": "invalido"}).status_code == 422
    d = client.post(f"{R}/orders/{o['id']}/dispute", headers=comp, json={"reasonCode": "not_received", "description": "O ingresso não chegou."}).json()
    assert d["status"] == "disputed" and d["dispute"]["status"] == "open" and d["canConfirm"] is False
    assert client.post(f"{R}/orders/{o['id']}/confirm", headers=comp).json()["code"] == "DISPUTED"
    rep = client.post(f"{R}/orders/{o['id']}/dispute/reply", headers=vend, json={"text": "Transferi pelo app."})
    assert rep.status_code == 200 and rep.json()["sellerReply"] == "Transferi pelo app."
    advance(hours=100)  # a disputa congela a liberação automática
    assert client.get(f"{R}/orders/{o['id']}", headers=comp).json()["status"] == "disputed"
    fila = client.get(f"{ADM}/disputes", headers=club_admin).json()
    disp = next(x for x in fila if x["orderId"] == o["id"])
    assert disp["order"]["buyerHandle"].startswith("@cd1") and disp["reasonCode"] == "not_received"
    assert client.post(f"{ADM}/disputes/{disp['id']}/decide", headers=fan, json={"decision": "refund"}).status_code == 403  # fã não decide
    assert client.post(f"{ADM}/disputes/{disp['id']}/decide", headers=vend, json={"decision": "release"}).status_code == 403
    out = client.post(f"{ADM}/disputes/{disp['id']}/decide", headers=club_admin, json={"decision": "refund", "note": "Sem prova de entrega"}).json()
    assert out["status"] == "resolved" and out["resolution"] == "refund" and out["order"]["status"] == "refunded"
    led = ledger(client, club_admin, o["id"])
    assert led["refund"]["amountCents"] == 18000 and "release_seller" not in led
    assert client.post(f"{ADM}/disputes/{disp['id']}/decide", headers=club_admin, json={"decision": "release"}).status_code == 409


def test_disputa_liberada_ao_vendedor(client, club_admin, world):
    vend, comp, o = _transferred_order(client, club_admin, world, "d2")
    client.post(f"{R}/orders/{o['id']}/dispute", headers=comp, json={"reasonCode": "other"})
    disp = next(x for x in client.get(f"{ADM}/disputes", headers=club_admin).json() if x["orderId"] == o["id"])
    out = client.post(f"{ADM}/disputes/{disp['id']}/decide", headers=club_admin, json={"decision": "release"}).json()
    assert out["order"]["status"] == "completed" and out["order"]["closeReason"] == "dispute_release"
    led = ledger(client, club_admin, o["id"])
    assert led["release_seller"]["amountCents"] + (led["fee"]["amountCents"] if "fee" in led else 0) == 18000 and "refund" not in led
    assert not client.get(f"{ADM}/disputes", headers=club_admin).json() or o["id"] not in [x["orderId"] for x in client.get(f"{ADM}/disputes", headers=club_admin).json()]


def test_admin_nao_decide_disputa_em_que_e_parte(client, club_admin, world):
    """O admin do ambiente (vintage@) comprando o próprio pedido não pode decidir a disputa dele."""
    vend = as_seller(client, "dadm")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal

    with SessionLocal() as db:  # o admin de teste precisa de cadastro completo e de Fandom para comprar
        u = db.scalar(select(m.User).where(m.User.email == "vintage@superfas.dev"))
        u.zip_code, u.street, u.number, u.neighborhood, u.city, u.state = "13000-000", "Rua A", "1", "Centro", "Campinas", "SP"
        art = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        if not db.scalar(select(m.Fandom.id).where(m.Fandom.artist_id == art.id, m.Fandom.user_id == u.id)):
            db.add(m.Fandom(artist_id=art.id, user_id=u.id))
        db.commit()
    assert client.get(f"{R}/me/eligibility", headers=club_admin).json()["canBuy"] is True
    o = reserve(client, club_admin, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=club_admin)
    client.post(f"{R}/orders/{o['id']}/transferred", headers=vend)
    client.post(f"{R}/orders/{o['id']}/dispute", headers=club_admin, json={"reasonCode": "other"})
    disp = next(x for x in client.get(f"{ADM}/disputes", headers=club_admin).json() if x["orderId"] == o["id"])
    res = client.post(f"{ADM}/disputes/{disp['id']}/decide", headers=club_admin, json={"decision": "refund"})
    assert res.status_code == 403 and res.json()["code"] == "CONFLICT_OF_INTEREST"


def test_admin_reembolsa_pedido_pago_e_nao_transferido(client, club_admin, world):
    vend, comp = as_seller(client, "adr"), register(client, "compadr")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    out = client.post(f"{ADM}/orders/{o['id']}/refund", headers=club_admin).json()
    assert out["status"] == "refunded" and out["closeReason"] == "admin_refund"
    assert client.post(f"{ADM}/orders/{o['id']}/refund", headers=club_admin).json()["status"] == "refunded"  # idempotente


# ---------------------------------------------------------------- integração com o resto do sistema


def test_nao_apaga_show_com_revenda_registrada(client, club_admin, world):
    r = client.delete(f"{ART}/manage/events/{world['event']}", headers=club_admin)
    assert r.status_code == 409 and r.json()["code"] == "HAS_RESALE"
    assert client.get(f"{ART}/manage/events", headers=club_admin).status_code == 200


def test_cancelar_anuncio_com_pedido_em_andamento_e_recusado(client, club_admin, world):
    vend, comp = as_seller(client, "canl"), register(client, "compcanl")
    li = new_listing(client, world, vend, qty=2, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    blocked = client.post(f"{R}/listings/{li['id']}/cancel", headers=vend)
    assert blocked.status_code == 409 and blocked.json()["code"] == "HAS_ACTIVE_ORDERS"
    client.post(f"{R}/orders/{o['id']}/cancel", headers=comp)
    assert client.post(f"{R}/listings/{li['id']}/cancel", headers=vend).json()["status"] == "cancelled"
    assert client.post(f"{R}/listings/{li['id']}/cancel", headers=vend).json()["status"] == "cancelled"
    assert reserve(client, comp, li["id"]).json()["code"] == "LISTING_NOT_LIVE"


def test_anuncio_de_outro_ambiente_ou_pedido_de_terceiro_nao_vaza(client, club_admin, world):
    vend, comp, intruso = as_seller(client, "iso"), register(client, "compiso"), register(client, "intruso")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    assert client.get(f"{R}/orders/{o['id']}", headers=intruso).status_code == 404
    assert client.post(f"{R}/orders/{o['id']}/confirm", headers=intruso).status_code == 404
    assert client.get(f"/artists/nao-existe/resale/events", headers=comp).status_code == 404


def test_varredura_global_so_para_o_master(client, master, fan):
    assert client.post("/resale/maintenance/sweep", headers=fan).status_code == 403
    assert client.post("/resale/maintenance/sweep", headers=master).status_code == 200


def test_webhook_do_provedor_simulado_e_recusado(client):
    assert client.post("/resale/payments/webhook/fake", content=b"{}").status_code == 400
    assert client.post("/resale/payments/webhook/outro", content=b"{}").status_code == 404


# ---------------------------------------------------------------- achados da revisão independente


def test_pagamento_simulado_so_liga_fora_do_sqlite_com_a_chave_explicita(client, club_admin, world, monkeypatch):
    from app.config import get_settings
    from app.resale import payments

    vend, comp = as_seller(client, "fk"), register(client, "compfk")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    monkeypatch.setattr(payments, "is_dev_db", lambda: False)  # como no servidor (Postgres)
    monkeypatch.setattr(get_settings(), "resale_allow_fake_payment", False)
    assert client.get(f"{R}/orders/{o['id']}", headers=comp).json()["canPay"] is False  # o front nem oferece o botão
    r = client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    assert r.status_code == 404 and r.json()["code"] == "NOT_AVAILABLE"
    monkeypatch.setattr(get_settings(), "resale_allow_fake_payment", True)  # RESALE_ALLOW_FAKE_PAYMENT=true
    assert client.post(f"{R}/orders/{o['id']}/pay", headers=comp).json()["status"] == "awaiting_transfer"


def test_fora_do_dev_cpf_e_codigos_exigem_chaves_proprias(client, monkeypatch):
    from app.config import get_settings

    h = register(client, "chaves")
    monkeypatch.setattr(rb, "is_dev_db", lambda: False)
    monkeypatch.setattr(get_settings(), "resale_pii_key", "")
    monkeypatch.setattr(get_settings(), "resale_pepper", "")
    r = client.put("/me/identity", headers=h, json={"cpf": make_cpf(314159265), "phone": "19999991234"})
    assert r.status_code == 503 and r.json()["code"] == "KEYS_MISSING"


def test_pagamento_tardio_em_pedido_cancelado_e_valor_divergente(client, club_admin, world):
    from app.db import SessionLocal
    from app.resale import orders as ro
    from app.resale.base import ResaleError
    from app.resale.models import Order

    vend, comp = as_seller(client, "tardio"), register(client, "comptardio")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    client.post(f"{R}/orders/{o['id']}/cancel", headers=comp)
    with SessionLocal() as db:
        order = db.get(Order, o["id"])
        with pytest.raises(ResaleError) as bad:  # valor pago diferente do pedido
            ro.confirm_payment(db, order, "ref-1", amount_cents=order.gross_cents - 1)
        assert bad.value.code == "AMOUNT_MISMATCH"
        ro.confirm_payment(db, order, "ref-2", amount_cents=order.gross_cents)  # o PIX compensou depois de cancelar
        assert db.get(Order, o["id"]).status == "refunded" and db.get(Order, o["id"]).close_reason == "late_payment"
        ro.confirm_payment(db, order, "ref-2", amount_cents=order.gross_cents)  # webhook repetido não duplica
    led = ledger(client, club_admin, o["id"])
    assert led["hold"]["amountCents"] == led["refund"]["amountCents"] == 18000 and len(led) == 2


def test_admin_nao_analisa_o_proprio_anuncio(client, club_admin, world):
    client.put("/me/identity", headers=club_admin, json={"cpf": make_cpf(246813579), "phone": "(19) 98888-7777"})
    # o admin de teste precisa de cadastro completo e Fandom para vender (o teste de disputa já os criou)
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal

    with SessionLocal() as db:
        u = db.scalar(select(m.User).where(m.User.email == "vintage@superfas.dev"))
        u.zip_code, u.street, u.number, u.neighborhood, u.city, u.state = "13000-000", "Rua A", "1", "Centro", "Campinas", "SP"
        art = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        if not db.scalar(select(m.Fandom.id).where(m.Fandom.artist_id == art.id, m.Fandom.user_id == u.id)):
            db.add(m.Fandom(artist_id=art.id, user_id=u.id))
        db.commit()
    li = new_listing(client, world, club_admin, qty=1)
    for acao in ("approve", "reject"):
        r = client.post(f"{ADM}/listings/{li['id']}/{acao}", headers=club_admin, json={"reason": "x"})
        assert r.status_code == 403 and r.json()["code"] == "CONFLICT_OF_INTEREST"


def test_cancelar_anuncio_depois_de_venda_nao_libera_os_codigos(client, club_admin, world):
    vend, comp = as_seller(client, "cod"), register(client, "compcod")
    codes = ["VENDIDO0001", "VENDIDO0002"]
    li = new_listing(client, world, vend, qty=2, approve_with=club_admin, codes=codes)
    o = reserve(client, comp, li["id"], qty=1).json()
    client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    client.post(f"{R}/orders/{o['id']}/transferred", headers=vend)
    client.post(f"{R}/orders/{o['id']}/confirm", headers=comp)
    assert client.post(f"{R}/listings/{li['id']}/cancel", headers=vend).json()["status"] == "cancelled"
    # um dos códigos já foi entregue: nenhum deles volta a poder ser anunciado
    outro = as_seller(client, "reanuncio")
    r = client.post(f"{R}/events/{world['event']}/listings", headers=outro, data={"ticketId": world["ticket"], "qty": 1, "unitPriceCents": 100, "codes": ["vendido0001"]}, files=proof())
    assert r.status_code == 409 and r.json()["code"] == "CODE_DUPLICATE"


def test_show_com_so_as_chaves_nao_apaga_e_data_nao_muda_com_compra_em_andamento(client, club_admin, world):
    ev = client.post(f"{ART}/manage/events", headers=club_admin, json={"date": "2031-11-11", "city": "So chaves", "time": "22h"}).json()
    client.put(f"{ADM}/events/{ev['id']}", headers=club_admin, json={"ticketingSoldOut": True, "resaleOpen": True})
    assert client.delete(f"{ART}/manage/events/{ev['id']}", headers=club_admin).json()["code"] == "HAS_RESALE"
    vend, comp = as_seller(client, "mud"), register(client, "compmud")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    reserve(client, comp, li["id"])
    r = client.patch(f"{ART}/manage/events/{world['event']}", headers=club_admin, json={"time": "18h"})
    assert r.status_code == 409 and r.json()["code"] == "CHANGE_BLOCKED"
    assert client.patch(f"{ART}/manage/events/{ev['id']}", headers=club_admin, json={"venue": "Outro lugar"}).status_code == 200  # outros campos seguem livres


def test_falha_do_provedor_nao_derruba_leituras_e_o_lancamento_e_refeito(client, club_admin, world, monkeypatch):
    from sqlalchemy import select

    from app.config import get_settings
    from app.db import SessionLocal
    from app.resale import payments
    from app.resale.models import LedgerEntry, Order

    vend, comp = as_seller(client, "falha"), register(client, "compfalha")
    li = new_listing(client, world, vend, qty=1, approve_with=club_admin)
    o = reserve(client, comp, li["id"]).json()
    calls = []

    def boom(self, order, idem):
        calls.append(idem)
        raise RuntimeError("gateway fora do ar")

    monkeypatch.setattr(payments.FakeProvider, "hold", boom)
    paid = client.post(f"{R}/orders/{o['id']}/pay", headers=comp)
    assert paid.status_code == 200 and paid.json()["status"] == "awaiting_transfer"  # o estado avançou; o lançamento ficou pendente
    assert ledger(client, club_admin, o["id"])["hold"]["status"] == "pending"
    # provedor mal configurado: leituras continuam funcionando (a falha não propaga)
    monkeypatch.setattr(get_settings(), "resale_payment_provider", "inexistente")
    assert client.get(f"{R}/me/orders", headers=comp).status_code == 200 and client.get(f"{R}/orders/{o['id']}", headers=comp).status_code == 200
    monkeypatch.setattr(get_settings(), "resale_payment_provider", "fake")
    monkeypatch.undo()
    # varredura seguinte refaz o lançamento, uma única vez
    with SessionLocal() as db:
        order = db.get(Order, o["id"])
        payments.settle(db, order)
        payments.settle(db, order)
        e = db.scalar(select(LedgerEntry).where(LedgerEntry.order_id == o["id"], LedgerEntry.kind == "hold"))
        assert e.status == "settled" and e.provider_ref.startswith("fake-hold-")
    assert len(calls) == 1 and ledger(client, club_admin, o["id"])["hold"]["status"] == "settled"
