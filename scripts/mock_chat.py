"""Cria conversas de exemplo no chat privado da conta de demonstração com outros fãs do ambiente Vintage Culture,
para a tela de mensagens já abrir com conversa (algumas com mensagem não lida).

No servidor (a pasta `scripts` não vai dentro do container, então o arquivo entra pela entrada padrão):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_chat.py

No seu computador:

    PYTHONPATH=. .venv/Scripts/python scripts/mock_chat.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_chat.py          # Linux/Mac

A conta de demonstração vem de DEMO_EMAIL (padrão: a fã de contas_vintage.py; se não existir, fa@superfas.dev):

    sudo docker compose exec -T -e DEMO_EMAIL='alguem@exemplo.com' api python - < ../back-super-fas/scripts/mock_chat.py

Pode rodar de novo: apaga só as conversas da conta de demonstração neste ambiente e cria de novo.
"""

import os
import random
from datetime import timedelta

from sqlalchemy import delete, or_, select

from app import models as m
from app.db import SessionLocal

ARTIST = "vintage-culture"
DEMO_EMAIL = os.environ.get("DEMO_EMAIL", "juliacristinalopes2607@gmail.com")
FALLBACK_EMAIL = "fa@superfas.dev"

# Cada conversa: falas em ordem; "eu" = conta de demonstração, "ele" = o outro fã.
# As três primeiras são as mais recentes e terminam com mensagem do outro ainda não lida.
CONVERSAS = [
    [
        ("ele", "Oi! Vi teu post no mural sobre a caravana, ainda tem vaga?"),
        ("eu", "Oii! Tem sim, sobraram 3 lugares na van"),
        ("ele", "Perfeito, quero 2. Eu e minha irmã"),
        ("eu", "Fechado! Saída às 19h da praça, combinado?"),
        ("ele", "Combinado demais"),
        ("ele", "Vou levar a bandeira do fã clube"),
        ("ele", "Será que ele toca Free ou só as novas?"),
    ],
    [
        ("eu", "Você foi no show de Floripa mês passado?"),
        ("ele", "Fui!! Foi surreal, o pôr do sol com o set dele"),
        ("eu", "Que inveja, não consegui ir dessa vez"),
        ("ele", "No próximo a gente vai junto, prometo"),
        ("eu", "Vou cobrar hein kkkk"),
        ("ele", "Pode cobrar! Inclusive já viu que abriu a pré-venda do próximo?"),
        ("ele", "Corre que o primeiro lote acaba rápido"),
    ],
    [
        ("ele", "Ei, tu tá participando do ranking Fã Super?"),
        ("eu", "Tô sim, compartilhei uns posts essa semana"),
        ("ele", "Eu tô quase no top 10, falta pouco"),
        ("eu", "Boa!! Qual o segredo?"),
        ("ele", "Compartilhar todo drop novo assim que sai, no mesmo dia"),
        ("eu", "Vou fazer isso então"),
        ("ele", "Saiu drop novo agora há pouco, aproveita"),
    ],
    [
        ("eu", "Oi! Você é do fã clube de BH, né?"),
        ("ele", "Sou sim! Tudo bem?"),
        ("eu", "Tudo ótimo. Vou me mudar pra BH mês que vem e queria colar nos encontros"),
        ("ele", "Que demais! A gente se encontra quase todo sábado antes das festas"),
        ("ele", "Te adiciono no grupo quando chegar"),
        ("eu", "Muito obrigada, de verdade"),
        ("ele", "Imagina, a galera é muito receptiva. Bem-vinda!"),
    ],
    [
        ("ele", "Qual a tua track favorita dele?"),
        ("eu", "Difícil... acho que Wild Kidz"),
        ("ele", "Boa escolha! A minha é Commotion"),
        ("eu", "Essa no festival foi absurda"),
        ("ele", "O drop dessa no sistema de som grande é outra coisa"),
        ("eu", "Arrepio só de lembrar"),
        ("ele", "Tomara que ele feche o próximo show com ela"),
        ("eu", "Seria perfeito"),
    ],
    [
        ("eu", "Conseguiu girar a roleta hoje?"),
        ("ele", "Consegui! Ganhei um cupom de 15% na loja"),
        ("eu", "Que sorte, eu só ganhei giro extra"),
        ("ele", "Giro extra também é bom, tenta de novo amanhã"),
        ("eu", "Vou tentar! Tô de olho no moletom novo"),
        ("ele", "Aquele preto? Lindo demais"),
    ],
    [
        ("ele", "Oi! Vi que você vai no show de São Paulo também"),
        ("eu", "Vou sim! Pista ou camarote?"),
        ("ele", "Pista, sempre. O som chega melhor lá na frente"),
        ("eu", "Concordo total. Bora marcar de se encontrar?"),
        ("ele", "Bora! Perto da torre de som do lado esquerdo"),
        ("eu", "Fechou, levo o cartaz do fã clube pra você achar"),
        ("ele", "Perfeito, até lá!"),
    ],
    [
        ("eu", "Oi! Obrigada por curtir minha foto do show"),
        ("ele", "Imagina! Ficou muito boa, que lugar você tava?"),
        ("eu", "Bem na grade, cheguei 4h antes kkkk"),
        ("ele", "Isso que é dedicação"),
        ("eu", "Valeu cada minuto"),
    ],
]


def pick_demo(db) -> m.User | None:
    for email in (DEMO_EMAIL, FALLBACK_EMAIL):
        u = db.scalar(select(m.User).where(m.User.email == email))
        if u:
            return u
    return None


def pick_fans(db, artist: m.Artist, demo: m.User, n: int) -> list[m.User]:
    """Fãs deste ambiente (com foto de perfil primeiro), sem a conta de demonstração."""
    fans = list(
        db.scalars(
            select(m.User)
            .join(m.Fandom, m.Fandom.user_id == m.User.id)
            .where(m.Fandom.artist_id == artist.id, m.User.role == m.ROLE_FAN, m.User.id != demo.id)
        )
    )
    rnd = random.Random(7)
    rnd.shuffle(fans)
    fans.sort(key=lambda u: not u.avatar_path)  # quem tem foto vem antes (a ordem embaralhada se mantém)
    return fans[:n]


def main() -> None:
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            print(f"Ambiente {ARTIST} não encontrado.")
            return
        demo = pick_demo(db)
        if not demo:
            print(f"Conta de demonstração não encontrada ({DEMO_EMAIL} nem {FALLBACK_EMAIL}).")
            return
        fans = pick_fans(db, artist, demo, len(CONVERSAS))
        if not fans:
            print("Nenhum outro fã neste ambiente para conversar.")
            return

        # Apaga as conversas da conta de demonstração neste ambiente (mensagens primeiro: o SQLite não apaga em cascata).
        old = list(
            db.scalars(
                select(m.Conversation.id).where(
                    m.Conversation.artist_id == artist.id,
                    or_(m.Conversation.user_a_id == demo.id, m.Conversation.user_b_id == demo.id),
                )
            )
        )
        if old:
            db.execute(delete(m.Message).where(m.Message.conversation_id.in_(old)))
            db.execute(delete(m.Conversation).where(m.Conversation.id.in_(old)))
            db.flush()

        rnd = random.Random(42)
        now = m.now()
        # A conversa mais recente terminou há poucos minutos; as outras vão ficando para trás (horas, depois dias).
        ends = [timedelta(minutes=4), timedelta(minutes=38), timedelta(hours=2, minutes=15), timedelta(hours=7),
                timedelta(days=1, hours=3), timedelta(days=2, hours=5), timedelta(days=4), timedelta(days=6, hours=2)]
        total = unread = 0
        for i, (other, falas) in enumerate(zip(fans, CONVERSAS)):
            a, b = sorted((demo.id, other.id))
            conv = m.Conversation(artist_id=artist.id, user_a_id=a, user_b_id=b)
            db.add(conv)
            db.flush()
            # Horários de trás para frente a partir do fim da conversa, com 1 a 25 minutos entre as falas.
            t = now - ends[i]
            stamps = []
            for _ in falas:
                stamps.append(t)
                t -= timedelta(minutes=rnd.randint(1, 25), seconds=rnd.randint(0, 59))
            stamps.reverse()
            # Nas três primeiras, as falas finais do outro (as que vêm depois da última da demo) ficam não lidas.
            last_mine = max((k for k, (who, _t) in enumerate(falas) if who == "eu"), default=-1)
            conv.created_at = stamps[0] - timedelta(minutes=1)
            for k, ((who, texto), ts) in enumerate(zip(falas, stamps)):
                sender = demo if who == "eu" else other
                pending = i < 3 and who == "ele" and k > last_mine
                read_at = None if pending else ts + timedelta(minutes=rnd.randint(1, 10))
                if read_at and read_at > now:
                    read_at = now
                db.add(m.Message(conversation_id=conv.id, sender_id=sender.id, body=texto, created_at=ts, read_at=read_at))
                total += 1
                unread += pending
            conv.last_message_at = stamps[-1]
        db.commit()
        print(f"{demo.email}: {min(len(fans), len(CONVERSAS))} conversas, {total} mensagens, {unread} não lidas.")


if __name__ == "__main__":
    main()
