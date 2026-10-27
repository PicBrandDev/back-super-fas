"""Faz o usuário da demonstração seguir fã clubes suficientes para a Comunidade dele ter pelo menos MIN_POSTS posts
(padrão 16), para o post patrocinado aparecer nas posições 8 e 16 do feed (um a cada 7 posts).

A Comunidade do fã mostra os 100 posts mais recentes do cantor (GET /artists/{slug}/posts) que são de um fã clube que
ele segue; os oficiais (Drop News) contam como do fã clube master. O script garante o master e depois entra nos fã
clubes ativos com mais posts entre esses 100 até seguir pelo menos MIN_CLUBES deles (padrão 2, para o feed não ter só
post oficial) e passar de MIN_POSTS. Usuário da demo: DEMO_EMAIL, padrão a conta de
fã juliacristinalopes2607@gmail.com (ou fa@superfas.dev, se ela não existir). Escreve direto no banco:

    PYTHONPATH=. .venv/Scripts/python scripts/demo_segue_clubes.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/demo_segue_clubes.py          # Linux/Mac

No servidor: sudo docker compose exec -T api python - < ../back-super-fas/scripts/demo_segue_clubes.py

Rode depois dos mocks de fã clubes e feed (o popular_demo.sh já faz isso). Pode rodar de novo: só entra nos fã clubes
que faltam e nunca sai de nenhum. Atenção: se o usuário da demo for dono ou ajudante de um fã clube, a Comunidade dele
mostra só esse fã clube (visão de dono) e seguir outros não muda nada; o script avisa.
"""

import os
from collections import Counter

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

ARTIST = os.environ.get("ARTIST", "vintage-culture")
DEMO_EMAIL = os.environ.get("DEMO_EMAIL", "")
DEMO_FALLBACK = ("juliacristinalopes2607@gmail.com", "fa@superfas.dev")
MIN_POSTS = int(os.environ.get("MIN_POSTS", "16"))
MIN_CLUBES = int(os.environ.get("MIN_CLUBES", "2"))  # fã clubes além do master
AD_EVERY = 7  # COMMUNITY_AD_EVERY do front: patrocinado depois de cada 7 posts
FEED_LIMIT = 100  # o mesmo limite de GET /artists/{slug}/posts


def main() -> None:
    db = SessionLocal()
    try:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            print(f"! cantor {ARTIST} não existe: nada a fazer")
            return
        demo = None
        for email in ([DEMO_EMAIL] if DEMO_EMAIL else list(DEMO_FALLBACK)):
            demo = db.scalar(select(m.User).where(m.User.email == email))
            if demo:
                break
        if not demo:
            print(f"! a conta {DEMO_EMAIL or ' / '.join(DEMO_FALLBACK)} não existe: rode o contas_vintage.py antes")
            return

        clubs = {c.id: c for c in artist.clubs}
        master = next((c for c in artist.clubs if c.is_master), None)
        staff = [c.name for c in artist.clubs if any(st.user_id == demo.id for st in c.staff)]
        if staff:
            print(f"! {demo.email} é da equipe de {', '.join(staff)}: a Comunidade dele mostra só esse(s) fã clube(s)")

        # Posts que a Comunidade recebe, contados pelo fã clube a que pertencem (o oficial é do master).
        posts = db.scalars(
            select(m.Post).where(m.Post.artist_id == artist.id).order_by(m.Post.created_at.desc()).limit(FEED_LIMIT)
        ).all()
        per_club: Counter[str] = Counter()
        for p in posts:
            if p.club_id in clubs:
                per_club[p.club_id] += 1
            elif master and (p.official or not p.author_id or p.kind == "drop"):
                per_club[master.id] += 1

        followed = set(db.scalars(select(m.ClubMember.club_id).where(m.ClubMember.user_id == demo.id)))
        followed &= set(clubs)

        def total() -> int:
            return sum(per_club[cid] for cid in followed)

        def follow(c: m.FanClub) -> None:
            db.add(m.ClubMember(club_id=c.id, user_id=demo.id))
            followed.add(c.id)
            print(f"+ {demo.email} agora segue {c.name} ({per_club[c.id]} posts)")

        if master and master.id not in followed:
            follow(master)
        # Os ativos com mais posts primeiro (empate: a ordem da lista de fã clubes).
        candidates = sorted(
            (c for c in artist.clubs if c.status == "active" and c.id not in followed and per_club[c.id]),
            key=lambda c: (-per_club[c.id], c.position, c.created_at),
        )
        for c in candidates:
            extra = sum(1 for cid in followed if not clubs[cid].is_master)
            if total() >= MIN_POSTS and extra >= MIN_CLUBES:
                break
            follow(c)
        db.commit()

        n = total()
        names = [clubs[cid].name for cid in sorted(followed, key=lambda cid: (not clubs[cid].is_master, clubs[cid].position))]
        print(f"{demo.email} segue {len(followed)} fã clube(s): {', '.join(names)}")
        print(f"Comunidade dele: {n} posts, {n // AD_EVERY} patrocinado(s) no feed")
        if n < AD_EVERY:
            print(f"! menos de {AD_EVERY} posts: o patrocinado não aparece (rode o mock_feed.py / mock_fa_clubes.py)")
        elif n < MIN_POSTS:
            print(f"! só {n} posts em todos os fã clubes ativos: o patrocinado aparece só na posição 8")
    finally:
        db.close()


if __name__ == "__main__":
    main()
