"""Quantas fotos faltam para o app ficar completo (só leitura: não altera nada).

Conta, para o ambiente vintage-culture:
  - posts: com foto de verdade, marcados com foto mas sem arquivo (mostram o espaço vazio) e só de texto (não precisam);
  - usuários que aparecem nas telas (autores de post e de comentário, ranking do Instagram, donos e equipe de fã clube)
    com e sem foto de perfil;
  - fã clubes com e sem foto.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/relatorio_fotos.py
Para ver também os nomes, acrescente a variável LISTAR=1:
    sudo docker compose exec -T -e LISTAR=1 api python - < ../back-super-fas/scripts/relatorio_fotos.py
"""

import os

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

SLUG = os.environ.get("ARTIST", "vintage-culture")
LISTAR = os.environ.get("LISTAR") == "1"


def main() -> None:
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
        if not artist:
            raise SystemExit(f"ambiente {SLUG} não existe")
        club_ids = [c.id for c in db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id))]
        posts = list(db.scalars(select(m.Post).where((m.Post.artist_id == artist.id) | (m.Post.club_id.in_(club_ids)))))

        com_foto = [p for p in posts if p.image_path]
        sem_arquivo = [p for p in posts if not p.image_path and p.has_image]
        so_texto = [p for p in posts if not p.image_path and not p.has_image]
        print("POSTS")
        print(f"  total ........................ {len(posts)}")
        print(f"  com foto ..................... {len(com_foto)}")
        print(f"  marcados com foto, sem arquivo {len(sem_arquivo)}   <- faltam {len(sem_arquivo)} fotos de post")
        print(f"  só texto (não precisam) ...... {len(so_texto)}")
        if LISTAR:
            for p in sem_arquivo:
                print(f"    - [{p.kind}] {p.text[:60]!r}")

        ids = {p.author_id for p in posts if p.author_id}
        post_ids = [p.id for p in posts]
        if post_ids:
            ids |= {c.author_id for c in db.scalars(select(m.PostComment).where(m.PostComment.post_id.in_(post_ids))) if c.author_id}
        ids |= {s.user_id for s in db.scalars(select(m.InstagramShare).where(m.InstagramShare.artist_id == artist.id))}
        if club_ids:
            ids |= {s.user_id for s in db.scalars(select(m.ClubStaff).where(m.ClubStaff.club_id.in_(club_ids)))}
        users = list(db.scalars(select(m.User).where(m.User.id.in_(ids)))) if ids else []
        sem = [u for u in users if not u.avatar_path]
        print("\nUSUÁRIOS QUE APARECEM NAS TELAS (autores, comentaristas, ranking, donos e equipe)")
        print(f"  total ........................ {len(users)}")
        print(f"  com foto de perfil ........... {len(users) - len(sem)}")
        print(f"  sem foto de perfil ........... {len(sem)}   <- faltam {len(sem)} fotos de perfil")
        if LISTAR:
            for u in sorted(sem, key=lambda u: u.name):
                print(f"    - {u.name} ({u.handle or u.email})")

        clubs = list(db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id)))
        sem_c = [c for c in clubs if not c.avatar_path]
        print("\nFÃ CLUBES")
        print(f"  total ........................ {len(clubs)}")
        print(f"  sem foto ..................... {len(sem_c)}   <- faltam {len(sem_c)} fotos de fã clube")
        if LISTAR:
            for c in sem_c:
                print(f"    - {c.name}")

        total = len(sem_arquivo) + len(sem) + len(sem_c)
        print(f"\nTOTAL QUE FALTA: {total} fotos ({len(sem_arquivo)} de post, {len(sem)} de perfil, {len(sem_c)} de fã clube)")


main()
