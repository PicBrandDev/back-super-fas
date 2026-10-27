"""Dados de teste para os detalhes do Drop News e do Drops Hits no admin (comentários, quem compartilhou e visualizações).

O que faz, direto no banco, no ambiente vintage-culture:
  - Drop News (posts oficiais): comentários de fãs (de 12 a 40 por post) e compartilhamentos com a hashtag
    (de 20 a 70 por post; poucos já confirmados no Instagram, a maioria aguardando);
  - Drops Hits (faixas): curtidas (votos), visualizações e compartilhamentos.

Pode rodar de novo: apaga o que ele mesmo criou (compartilhamentos com link "mock" e comentários com as frases dele)
e cria de novo. Não mexe no que os fãs fizeram de verdade. Atenção: os compartilhamentos confirmados somam pontos no
ranking Fã Super (são poucos, uns 12%); com CONFIRMADOS=0 todos ficam aguardando conferência e o ranking não muda.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_conteudo.py
"""

import os
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app import models as m
from app.db import SessionLocal

SLUG = os.environ.get("ARTIST", "vintage-culture")
CONFIRMED_SHARE = 0.0 if os.environ.get("CONFIRMADOS") == "0" else 0.12
MARK = "https://instagram.com/p/mock"

COMMENTS = [
    "Que noite foi essa!",
    "Quero muito ir no próximo",
    "Melhor set do ano, sem discussão",
    "Já garanti meu ingresso",
    "Quem mais vai de caravana?",
    "Esse drop ficou absurdo",
    "Voltem logo pra cá!",
    "Chorei na hora do drop kkk",
    "Alguém tem foto desse momento?",
    "Mandou muito bem, parabéns",
    "Preciso dessa prévia completa",
    "O Photo Finder me achou na pista, amei",
    "Vou levar a galera toda",
    "Setlist perfeita",
    "Esse som no carro é outro nível",
    "Sonhando com o próximo show",
    "Fã clube de BH presente!",
    "Salvador tá pronta pra receber",
    "Que energia, que produção",
    "Já ouvi umas vinte vezes",
    "Quando sai a versão completa?",
    "Melhor fã clube que existe",
    "Me arrepiei de novo vendo isso",
    "Show de bola, valeu Vintage!",
]


def main() -> None:
    rnd = random.Random(7)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
        if not artist:
            raise SystemExit(f"ambiente {SLUG} não existe")
        fans = [f.user_id for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id))]
        posts = list(db.scalars(select(m.Post).where(m.Post.artist_id == artist.id, m.Post.official.is_(True), m.Post.kind == "drop")))
        tracks = list(db.scalars(select(m.Track).where(m.Track.artist_id == artist.id).order_by(m.Track.position)))

        # limpa a rodada anterior
        db.execute(delete(m.InstagramShare).where(m.InstagramShare.artist_id == artist.id, m.InstagramShare.permalink.like(f"{MARK}%")))
        if posts:
            db.execute(delete(m.PostComment).where(m.PostComment.post_id.in_([p.id for p in posts]), m.PostComment.text.in_(COMMENTS)))
        db.flush()

        n_comments = n_shares = 0

        def share_rows(post_id: str | None, track_id: str | None, how_many: int) -> None:
            nonlocal n_shares
            for k, user in enumerate(rnd.sample(fans, min(how_many, len(fans)))):
                at = now - timedelta(days=rnd.random() * 20, hours=rnd.random() * 8)
                r = rnd.random()
                st = "verified" if r < CONFIRMED_SHARE else ("claimed" if r < 0.7 else "started")
                db.add(
                    m.InstagramShare(
                        artist_id=artist.id, user_id=user, post_id=post_id, track_id=track_id, status=st, created_at=at,
                        permalink=f"{MARK}/{post_id or track_id}-{k}",
                        media_id=f"mock-{post_id or track_id}-{k}" if st == "verified" else None,
                        verified_at=at + timedelta(minutes=rnd.randint(5, 240)) if st == "verified" else None,
                    )
                )
                n_shares += 1

        for p in posts:
            mine = rnd.sample(fans, min(rnd.randint(12, 40), len(fans)))
            for user in mine:
                at = max(p.created_at.replace(tzinfo=p.created_at.tzinfo or timezone.utc), now - timedelta(days=20)) + timedelta(minutes=rnd.randint(2, 60 * 36))
                db.add(m.PostComment(post_id=p.id, author_id=user, text=rnd.choice(COMMENTS), created_at=min(at, now)))
                n_comments += 1
            p.comments = max(p.comments, len(mine))
            share_rows(p.id, None, rnd.randint(20, 70))

        for i, t in enumerate(tracks):
            t.views = rnd.randint(9_000, 64_000) - i * 700
            t.votes = max(t.votes, int(t.views * rnd.uniform(0.08, 0.31)))
            share_rows(None, t.id, rnd.randint(25, 80))

        db.commit()
        print(f"pronto: {len(posts)} posts oficiais e {len(tracks)} hits; {n_comments} comentários e {n_shares} compartilhamentos criados.")


main()
