"""Chat privado entre fãs (só texto) e perfil público do fã. Contrato em docs/chat-api.md."""

import pytest

VC = "/artists/vintage-culture"
CHAT = f"{VC}/chat"


def _novo_fa(client, nome: str, handle: str) -> tuple[dict, str]:
    r = client.post(
        "/auth/register",
        json={
            "name": nome, "email": f"{handle}@chat.exemplo.com", "password": "12345678", "handle": handle, "artist": "vintage-culture",
            "zipCode": "30130-000", "street": "Av. Afonso Pena", "number": "1", "neighborhood": "Centro", "city": "Belo Horizonte", "state": "mg",
        },
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["id"]


@pytest.fixture(scope="module")
def trio(client):
    """Três fãs novos: dois que conversam e um de fora."""
    return _novo_fa(client, "Ana Chat", "ana.chat"), _novo_fa(client, "Bruno Chat", "bruno.chat"), _novo_fa(client, "Caio Chat", "caio.chat")


@pytest.fixture(scope="module")
def conversa(client, trio):
    (ha, _ia), (_hb, ib), _c = trio
    r = client.post(f"{CHAT}/conversations", headers=ha, json={"userId": ib})
    assert r.status_code == 200, r.text
    return r.json()


def test_inicia_conversa_e_reaproveita(client, trio, conversa):
    (ha, ia), (hb, ib), _c = trio
    assert conversa["other"] == {"id": ib, "name": "Bruno Chat", "handle": "@bruno.chat", "avatar": None}
    assert conversa["lastMessage"] is None and conversa["lastMessageAt"] is None and conversa["unread"] == 0
    # o mesmo par (nos dois sentidos, e em snake_case) cai na mesma conversa
    assert client.post(f"{CHAT}/conversations", headers=ha, json={"user_id": ib}).json()["id"] == conversa["id"]
    do_outro_lado = client.post(f"{CHAT}/conversations", headers=hb, json={"userId": ia}).json()
    assert do_outro_lado["id"] == conversa["id"] and do_outro_lado["other"]["id"] == ia
    assert client.get(f"{CHAT}/conversations/{conversa['id']}", headers=hb).json()["other"]["name"] == "Ana Chat"


def test_nao_conversa_consigo_nem_com_quem_nao_existe(client, trio):
    (ha, ia), _b, _c = trio
    r = client.post(f"{CHAT}/conversations", headers=ha, json={"userId": ia})
    assert r.status_code == 422 and "você mesmo" in r.json()["detail"]
    assert client.post(f"{CHAT}/conversations", headers=ha, json={"userId": "naoexiste00"}).status_code == 404
    assert client.get(f"{CHAT}/conversations", headers={}).status_code == 401
    assert client.get("/artists/nao-existe/chat/conversations", headers=ha).status_code == 404


def test_envia_e_faz_polling(client, trio, conversa):
    (ha, ia), (hb, _ib), _c = trio
    cid = conversa["id"]
    m1 = client.post(f"{CHAT}/conversations/{cid}/messages", headers=ha, json={"body": "  Bora no show de BH?  "})
    assert m1.status_code == 201, m1.text
    m1 = m1.json()
    assert m1["body"] == "Bora no show de BH?" and m1["mine"] is True and m1["senderId"] == ia and m1["conversationId"] == cid
    assert m1["readAt"] is None

    msgs = client.get(f"{CHAT}/conversations/{cid}/messages", headers=hb).json()
    assert [x["id"] for x in msgs] == [m1["id"]] and msgs[0]["mine"] is False

    m2 = client.post(f"{CHAT}/conversations/{cid}/messages", headers=hb, json={"body": "Vou sim! Chego às 22h na porta 3"}).json()
    m3 = client.post(f"{CHAT}/conversations/{cid}/messages", headers=hb, json={"body": "Leva o cartaz do VC"}).json()
    novas = client.get(f"{CHAT}/conversations/{cid}/messages?after_id={m1['id']}", headers=ha).json()
    assert [x["id"] for x in novas] == [m2["id"], m3["id"]]  # ordem crescente
    assert client.get(f"{CHAT}/conversations/{cid}/messages?after_id={m3['id']}", headers=ha).json() == []
    ultimas = client.get(f"{CHAT}/conversations/{cid}/messages?limit=2", headers=ha).json()
    assert [x["id"] for x in ultimas] == [m2["id"], m3["id"]]

    lista = client.get(f"{CHAT}/conversations", headers=ha).json()
    item = next(c for c in lista if c["id"] == cid)
    assert item["lastMessage"]["id"] == m3["id"] and item["lastMessageAt"] is not None


def test_nao_lidas_e_marcar_como_lida(client, trio, conversa):
    (ha, _ia), (hb, _ib), _c = trio
    cid = conversa["id"]
    client.post(f"{CHAT}/conversations/{cid}/read", headers=hb)
    antes = client.get(f"{CHAT}/unread", headers=ha).json()["count"]
    client.post(f"{CHAT}/conversations/{cid}/messages", headers=hb, json={"body": "Tá aí?"})
    assert client.get(f"{CHAT}/unread", headers=ha).json()["count"] == antes + 1
    item = next(c for c in client.get(f"{CHAT}/conversations", headers=ha).json() if c["id"] == cid)
    assert item["unread"] == antes + 1
    assert client.get(f"{CHAT}/unread", headers=hb).json()["count"] == 0  # as próprias não contam

    assert client.post(f"{CHAT}/conversations/{cid}/read", headers=ha).json() == {"unread": 0}
    assert client.get(f"{CHAT}/unread", headers=ha).json() == {"count": 0}
    assert client.get(f"{CHAT}/conversations/{cid}", headers=ha).json()["unread"] == 0
    # quem enviou vê que foi lida
    vistas = client.get(f"{CHAT}/conversations/{cid}/messages", headers=hb).json()
    assert all(x["readAt"] for x in vistas if x["mine"])


@pytest.mark.parametrize(
    "texto",
    [
        "olha essa foto https://exemplo.com/fotos/show.jpg",
        "https://cdn.exemplo.com/clip.MP4?token=abc",
        "www.exemplo.com/a.png",
        "data:image/png;base64,iVBORw0KGgo=",
        "vê aqui /uploads/real-user-123.webp",
        "https://superfas.com.br/uploads/arquivo",
    ],
)
def test_recusa_midia(client, trio, conversa, texto):
    (ha, _ia), _b, _c = trio
    r = client.post(f"{CHAT}/conversations/{conversa['id']}/messages", headers=ha, json={"body": texto})
    assert r.status_code == 422 and r.json()["detail"].startswith("O chat é só de texto")


def test_aceita_texto_comum_e_valida_tamanho(client, trio, conversa):
    (ha, _ia), _b, _c = trio
    url = f"{CHAT}/conversations/{conversa['id']}/messages"
    for ok in ["Qual a data: sábado ou domingo?", "o setlist tá em https://vintageculture.com/agenda", "arquivo.jpg é o nome do meu gato"]:
        assert client.post(url, headers=ha, json={"body": ok}).status_code == 201, ok
    assert client.post(url, headers=ha, json={"body": "   "}).status_code == 422
    assert client.post(url, headers=ha, json={"body": "a" * 1001}).status_code == 422
    assert client.post(url, headers=ha, json={"body": "a" * 1000}).status_code == 201


def test_quem_nao_participa_recebe_403(client, trio, conversa):
    _a, _b, (hc, _ic) = trio
    cid = conversa["id"]
    assert client.get(f"{CHAT}/conversations/{cid}", headers=hc).status_code == 403
    assert client.get(f"{CHAT}/conversations/{cid}/messages", headers=hc).status_code == 403
    assert client.post(f"{CHAT}/conversations/{cid}/messages", headers=hc, json={"body": "oi"}).status_code == 403
    assert client.post(f"{CHAT}/conversations/{cid}/read", headers=hc).status_code == 403
    assert client.get(f"{CHAT}/conversations/999999", headers=hc).status_code == 404
    assert all(c["id"] != cid for c in client.get(f"{CHAT}/conversations", headers=hc).json())


def test_perfil_publico_e_autor_do_post(client, trio):
    (ha, ia), (hb, _ib), _c = trio
    p = client.post(f"{VC}/posts", headers=ha, json={"kind": "galera", "text": "Caravana BH saindo da Savassi"})
    assert p.status_code == 201, p.text
    autor = p.json()["author"]
    assert autor["id"] == ia and autor["avatar"] is None and autor["handle"] == "@ana.chat"
    no_mural = next(x for x in client.get(f"{VC}/posts?kind=galera", headers=hb).json() if x["id"] == p.json()["id"])
    assert no_mural["author"]["id"] == ia

    perfil = client.get(f"{VC}/fans/{ia}", headers=hb)
    assert perfil.status_code == 200, perfil.text
    perfil = perfil.json()
    assert perfil["id"] == ia and perfil["name"] == "Ana Chat" and perfil["handle"] == "@ana.chat" and perfil["isMe"] is False
    assert perfil["club"] is not None and perfil["club"]["slug"]  # entrou no fã clube master no cadastro
    assert isinstance(perfil["points"], int) and perfil["rank"] is None
    assert [x["id"] for x in perfil["posts"]] == [p.json()["id"]]
    assert client.get(f"{VC}/fans/{ia}", headers=ha).json()["isMe"] is True
    assert client.get(f"{VC}/fans/naoexiste00", headers=ha).status_code == 404


def test_post_oficial_sem_id_de_autor(client, fan):
    oficial = [x for x in client.get(f"{VC}/posts", headers=fan).json() if x["kind"] == "drop"]
    assert oficial and all(x["author"]["id"] is None and x["author"]["avatar"] is None for x in oficial)


def test_so_conversa_com_fa_do_ambiente(client, trio):
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal

    (ha, _ia), _b, _c = trio
    # quem não é fã do ambiente (ex.: o admin master) não recebe conversa
    with SessionLocal() as db:
        fas = select(m.Fandom.user_id).join(m.Artist).where(m.Artist.slug == "vintage-culture")
        de_fora = db.scalar(select(m.User.id).where(m.User.id.not_in(fas)).limit(1))
    assert de_fora
    r = client.post(f"{CHAT}/conversations", headers=ha, json={"userId": de_fora})
    assert r.status_code == 404


def test_historico_antes_de_uma_mensagem(client, trio):
    (ha, _ia), _b, (_hc, ic) = trio
    conv = client.post(f"{CHAT}/conversations", headers=ha, json={"userId": ic}).json()
    url = f"{CHAT}/conversations/{conv['id']}/messages"
    ids = [client.post(url, headers=ha, json={"body": f"msg {n}"}).json()["id"] for n in range(5)]
    ultimas = client.get(f"{url}?limit=2", headers=ha).json()
    assert [x["id"] for x in ultimas] == ids[3:]
    antes = client.get(f"{url}?limit=2&before_id={ids[3]}", headers=ha).json()
    assert [x["id"] for x in antes] == ids[1:3]
    lista = {c["id"]: c for c in client.get(f"{CHAT}/conversations", headers=ha).json()}
    assert lista[conv["id"]]["lastMessage"]["id"] == ids[-1]
