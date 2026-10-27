"""Módulo "resale": a revenda saiu do app e fica escondida. Desligada por padrão, responde 404 para o fã;
a área de admin da revenda continua acessível e ligar o módulo no admin master traz tudo de volta."""

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal, engine
from app.migrations import upgrade

ART = "/artists/vintage-culture"
R = f"{ART}/resale"


def set_resale(client, master, on: bool):
    r = client.patch("/admin/fan-clubs/vintage-culture", headers=master, json={"modules": {"resale": on}})
    assert r.status_code == 200 and r.json()["modules"]["resale"] is on, r.text


def test_fa_clube_novo_nasce_com_a_revenda_desligada(client, master):
    r = client.post("/admin/fan-clubs", headers=master, json={"name": "Revenda Off", "instagram": "@revendaoff", "invites": []})
    assert r.status_code == 201, r.text
    mods = r.json()["artist"]["modules"]
    assert mods["resale"] is False and mods["ads"] is True


def test_revenda_desligada_responde_404_para_o_fa(client, master, fan, club_admin):
    set_resale(client, master, False)
    for path in ("/events", "/me/eligibility", "/me/listings", "/me/orders", "/listings/nao-existe", "/sellers/nao-existe"):
        r = client.get(f"{R}{path}", headers=fan)
        assert r.status_code == 404, (path, r.text)
        assert r.json()["code"] == "NOT_FOUND"
    assert client.post(f"{R}/listings/nao-existe/orders", headers=fan, json={"qty": 1}).status_code == 404
    # A área de admin da revenda continua de pé (a equipe e o admin master ainda enxergam).
    assert client.get(f"{R}/admin/events", headers=club_admin).status_code == 200
    assert client.get(f"{R}/admin/events", headers=master).status_code == 200


def test_revenda_ligada_no_admin_volta_a_responder(client, master, fan):
    set_resale(client, master, True)
    try:
        assert client.get(f"{R}/events", headers=fan).status_code == 200
    finally:
        set_resale(client, master, False)


def test_migracao_grava_resale_desligado_so_em_quem_nao_tem_a_chave(client, master):
    with SessionLocal() as db:
        vc = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        vc.modules = {k: v for k, v in (vc.modules or {}).items() if k != "resale"}
        other = db.scalar(select(m.Artist).where(m.Artist.slug == "revenda-off"))
        other.modules = {**(other.modules or {}), "resale": True}
        db.commit()
    upgrade(engine)
    upgrade(engine)  # idempotente
    with SessionLocal() as db:
        vc = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        other = db.scalar(select(m.Artist).where(m.Artist.slug == "revenda-off"))
        assert vc.modules["resale"] is False and vc.modules["ads"] is True
        assert other.modules["resale"] is True
