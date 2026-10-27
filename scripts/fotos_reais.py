"""Troca as fotos de mentira dos mocks (degradês coloridos) por fotos de verdade, para a demonstração.

Lê as fotos de FOTOS_DIR (padrão /tmp/fotos), em três subpastas, sempre em ordem alfabética do nome do arquivo:
  - rostos/  fotos de perfil. `00-demo.*` vai para o usuário da apresentação (DEMO_EMAIL, padrão a conta de fã
             juliacristinalopes2607@gmail.com). As outras vão para quem aparece nas telas, nesta ordem: contas de teste,
             donos e equipe dos fã clubes, fãs do ranking do Instagram e, por fim, os demais autores de post e comentário;
  - posts/   fotos dos posts que têm imagem (mural oficial e fã clubes), por ordem de criação do post. Se faltar foto,
             os posts que sobram viram post só de texto (nenhuma foto se repete); sem nenhuma foto de post, os posts
             ficam como estão;
  - clubes/  foto de perfil dos fã clubes, por ordem do slug.
Sem Pillow no requirements: só aceita JPG, PNG ou WebP de até 5 MB (o mesmo limite do upload do admin) e copia o
arquivo como está para UPLOAD_DIR, com os nomes real-user-{id}.ext, real-post-{id}.ext e real-clube-{slug}.ext.

    PYTHONPATH=. FOTOS_DIR=./fotos .venv/Scripts/python scripts/fotos_reais.py      # Windows
    PYTHONPATH=. FOTOS_DIR=./fotos .venv/bin/python scripts/fotos_reais.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container; as fotos vão antes para /tmp/fotos do container):

    sudo docker compose cp ./fotos api:/tmp/fotos
    sudo docker compose exec -T api python - < ../back-super-fas/scripts/fotos_reais.py

Rode depois de todos os mocks (o popular_demo.sh já faz isso). Pode rodar de novo: com as mesmas fotos o resultado é o
mesmo. Usuários e fã clubes que ficam sem foto de verdade mantêm a que já tinham. Atenção: um post que virou só de texto
não volta a ter imagem se você acrescentar fotos depois (rode os mocks de novo num banco limpo para isso).
"""

import os
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal

ARTIST = os.environ.get("ARTIST", "vintage-culture")
FOTOS_DIR = Path(os.environ.get("FOTOS_DIR", "/tmp/fotos"))
DEMO_EMAIL = os.environ.get("DEMO_EMAIL", "")
DEMO_FALLBACK = ("juliacristinalopes2607@gmail.com", "fa@superfas.dev")
MAX_BYTES = 5 * 1024 * 1024
EXTS = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"}
# Contas de teste (seed.py e contas_vintage.py): recebem rosto antes de todo mundo.
SEEDS = (
    "admin@superfas.dev", "vintage@superfas.dev", "marca@superfas.dev", "fa@superfas.dev",
    "admin@vintage.com.br", "juliacristinalopes2607@gmail.com", "admin@fapage.com.br", "patrocinador@fapage.com.br",
)


def is_image(data: bytes, ext: str) -> bool:
    """Confere a assinatura do arquivo (não basta a extensão)."""
    if ext == ".jpg":
        return data[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def load(sub: str) -> list[tuple[Path, str]]:
    """Fotos válidas da subpasta, em ordem alfabética: [(arquivo, extensão final)]. As inválidas são puladas com aviso."""
    folder = FOTOS_DIR / sub
    if not folder.is_dir():
        print(f"! {folder} não existe: nenhuma foto de {sub}")
        return []
    out = []
    for f in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not f.is_file() or f.name.startswith("."):
            continue
        ext = EXTS.get(f.suffix.lower())
        if not ext:
            print(f"! {sub}/{f.name}: formato não aceito (use JPG, PNG ou WebP), pulei")
            continue
        if f.stat().st_size > MAX_BYTES:
            print(f"! {sub}/{f.name}: maior que 5 MB, pulei")
            continue
        with f.open("rb") as fh:
            head = fh.read(12)
        if not is_image(head, ext):
            print(f"! {sub}/{f.name}: não parece ser {ext[1:].upper()}, pulei")
            continue
        out.append((f, ext))
    return out


def copy(src: Path, ext: str, stem: str, uploads: Path) -> str:
    """Copia a foto para UPLOAD_DIR como `stem.ext` (só reescreve se mudou) e devolve o caminho público."""
    dest = uploads / f"{stem}{ext}"
    data = src.read_bytes()
    if not dest.is_file() or dest.read_bytes() != data:
        dest.write_bytes(data)
    for other in set(EXTS.values()) - {ext}:  # a mesma foto com outra extensão, de uma rodada anterior
        (uploads / f"{stem}{other}").unlink(missing_ok=True)
    return f"/uploads/{dest.name}"


def main() -> None:
    uploads = Path(get_settings().upload_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    rostos, fotos_posts, fotos_clubes = load("rostos"), load("posts"), load("clubes")
    demo_foto = next((x for x in rostos if x[0].stem.lower() == "00-demo"), None)
    rostos = [x for x in rostos if x is not demo_foto]

    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        clubs = list(db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id).order_by(m.FanClub.slug)))
        club_ids = [c.id for c in clubs]
        # Os mesmos posts e usuários que o relatorio_fotos.py conta.
        posts = list(
            db.scalars(
                select(m.Post)
                .where((m.Post.artist_id == artist.id) | (m.Post.club_id.in_(club_ids)))
                .order_by(m.Post.created_at, m.Post.id)
            )
        )
        authors = {p.author_id for p in posts if p.author_id}
        post_ids = [p.id for p in posts]
        if post_ids:
            authors |= {c.author_id for c in db.scalars(select(m.PostComment).where(m.PostComment.post_id.in_(post_ids))) if c.author_id}
        ranking = {s.user_id for s in db.scalars(select(m.InstagramShare).where(m.InstagramShare.artist_id == artist.id))}
        staff = {s.user_id for s in db.scalars(select(m.ClubStaff).where(m.ClubStaff.club_id.in_(club_ids)))} if club_ids else set()
        ids = authors | ranking | staff
        users = list(db.scalars(select(m.User).where(m.User.id.in_(ids)))) if ids else []

        # Usuário da apresentação.
        demo = None
        for email in ([DEMO_EMAIL] if DEMO_EMAIL else list(DEMO_FALLBACK)):
            demo = db.scalar(select(m.User).where(m.User.email == email))
            if demo:
                break
        if demo_foto and demo:
            demo.avatar_path = copy(*demo_foto, f"real-user-{demo.id}", uploads)
            print(f"+ usuário da demo ({demo.email}) ganhou {demo_foto[0].name}")
        elif demo_foto:
            print(f"! 00-demo sem dono: a conta {DEMO_EMAIL or ' / '.join(DEMO_FALLBACK)} não existe")
        else:
            print(f"! sem rostos/00-demo.*: o usuário da demo ({demo.email if demo else '?'}) ficou com a foto que já tinha")

        # Rostos: contas de teste, donos e equipe, ranking, demais autores (dentro de cada grupo, por ordem de cadastro).
        def group(u: m.User) -> int:
            if u.email in SEEDS:
                return 0
            if u.id in staff:
                return 1
            if u.id in ranking:
                return 2
            return 3

        fila = sorted((u for u in users if not demo or u.id != demo.id), key=lambda u: (group(u), u.created_at, u.id))
        for u, foto in zip(fila, rostos):
            u.avatar_path = copy(*foto, f"real-user-{u.id}", uploads)
        sem_rosto = fila[len(rostos):]
        print(f"+ {min(len(fila), len(rostos))} de {len(fila)} usuários das telas ganharam rosto de verdade")

        # Posts com imagem: um por foto, na ordem; os que sobram viram só texto. Sem nenhuma foto de post (pasta vazia
        # ou ausente) os posts ficam como estão, com a foto de mock: rodar sem fotos não apaga imagem de ninguém.
        com_imagem = [p for p in posts if p.image_path or p.has_image]
        for p, foto in zip(com_imagem, fotos_posts):
            p.image_path, p.has_image = copy(*foto, f"real-post-{p.id}", uploads), True
        viraram_texto = com_imagem[len(fotos_posts):] if fotos_posts else []
        for p in viraram_texto:
            p.image_path, p.has_image = "", False
        print(f"+ {min(len(com_imagem), len(fotos_posts))} de {len(com_imagem)} posts com imagem ganharam foto de verdade")

        # Fã clubes, por ordem do slug.
        for c, foto in zip(clubs, fotos_clubes):
            c.avatar_path = copy(*foto, f"real-clube-{c.slug}", uploads)
        print(f"+ {min(len(clubs), len(fotos_clubes))} de {len(clubs)} fã clubes ganharam foto de verdade")
        db.commit()

        print("\nRESUMO")
        print(f"  rostos: {len(rostos) + (1 if demo_foto else 0)} fotos para {len(fila)} usuários + o da demo", end="")
        if len(rostos) > len(fila):
            print(f"  -> sobraram {len(rostos) - len(fila)} fotos")
        elif sem_rosto:
            semfoto = sum(1 for u in sem_rosto if not u.avatar_path)
            print(f"  -> faltaram {len(sem_rosto)} fotos ({len(sem_rosto) - semfoto} ficam com a foto de mock, {semfoto} sem foto)")
        else:
            print("  -> na medida")
        print(f"  posts:  {len(fotos_posts)} fotos para {len(com_imagem)} posts com imagem", end="")
        if len(fotos_posts) > len(com_imagem):
            print(f"  -> sobraram {len(fotos_posts) - len(com_imagem)} fotos")
        elif viraram_texto:
            print(f"  -> faltaram {len(viraram_texto)} fotos: esses posts viraram só texto")
        elif not fotos_posts and com_imagem:
            print(f"  -> faltaram {len(com_imagem)} fotos (sem nenhuma, os posts ficam com a foto de mock)")
        else:
            print("  -> na medida")
        print(f"  clubes: {len(fotos_clubes)} fotos para {len(clubs)} fã clubes", end="")
        if len(fotos_clubes) > len(clubs):
            print(f"  -> sobraram {len(fotos_clubes) - len(clubs)} fotos")
        elif len(fotos_clubes) < len(clubs):
            print(f"  -> faltaram {len(clubs) - len(fotos_clubes)} fotos (ficam com a foto que já tinham)")
        else:
            print("  -> na medida")


if __name__ == "__main__":
    main()
