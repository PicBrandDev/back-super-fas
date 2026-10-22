"""Cria 5 fã clubes de exemplo no ambiente Vintage Culture, com donos, fãs de vários estados,
assinantes, posts com curtidas/comentários/visualizações e foto de perfil.

Escreve direto no banco (precisa de datas espalhadas nos últimos 30 dias para os gráficos):

    PYTHONPATH=. .venv/Scripts/python scripts/mock_fa_clubes.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_fa_clubes.py          # Linux/Mac

Pode rodar de novo: pula os fã clubes que já existem (mesmo nome). Donos e fãs de exemplo
entram com a senha "senha123".
"""

import colorsys
import random
import struct
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal
from app.routers.clubs import create_club
from app.security import hash_password

PASSWORD = "senha123"
ARTIST_SLUG = "vintage-culture"

# nome, cidade, UF, dono, cor do avatar (RGB), descrição
CLUBS = [
    ("Vintage Curitiba", "Curitiba", "PR", ("Marcos Vieira", "dono.curitiba@exemplo.com"), (231, 120, 23), "A galera de Curitiba: pré-baladas e caravana para os shows do sul."),
    ("Vintage BH", "Belo Horizonte", "MG", ("Luana Prado", "dono.bh@exemplo.com"), (186, 70, 26), "Mineiros do house: encontros, trocas de camiseta e muito pão de queijo."),
    ("Vintage Brasília", "Brasília", "DF", ("Thiago Nunes", "dono.brasilia@exemplo.com"), (67, 145, 184), "Fã clube do Planalto Central, com sorteios a cada show."),
    ("Vintage Salvador", "Salvador", "BA", ("Aline Souza", "dono.salvador@exemplo.com"), (252, 202, 11), "Baianos no mesmo ritmo: festas, fotos dos shows e caravanas."),
    ("Vintage Porto Alegre", "Porto Alegre", "RS", ("Gustavo Pereira", "dono.poa@exemplo.com"), (41, 73, 93), "Gaúchos fãs do Vintage Culture: churrasco, house e muita resenha."),
]

FIRST = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Felipe", "Gabi", "Henrique", "Isabela", "João", "Kátia", "Lucas", "Marina", "Nicolas", "Olívia", "Paulo", "Queila", "Rafael", "Sofia", "Tiago", "Ursula", "Vitor", "Wesley", "Yasmin", "Zeca"]
LAST = ["Almeida", "Barros", "Cardoso", "Dias", "Esteves", "Ferreira", "Gomes", "Hora", "Ito", "Jardim", "Klein", "Lopes", "Moura", "Neves", "Oliveira", "Pires", "Queiroz", "Ramos", "Silva", "Teixeira"]
STREETS = ["Rua das Flores", "Av. Brasil", "Rua da Música", "Rua XV de Novembro", "Av. Central", "Rua do Comércio", "Rua Bahia", "Av. Paulista"]
HOODS = ["Centro", "Jardim América", "Vila Nova", "Boa Vista", "Santa Cruz", "São José"]
POSTS = [
    "Quem vai no próximo show? Bora combinar a caravana!",
    "Fui no show de ontem e ainda estou sem voz. Que noite!",
    "Alguém tem a lista de faixas do último set? Preciso rever.",
    "Primeira vez no fã clube, já amei a galera daqui.",
    "Vamos fazer um encontro antes do show? Sugestões de bar?",
    "Troco camiseta tamanho M por G, alguém topa?",
    "Esse drop novo é o melhor do ano, não aceito discussão.",
    "Quem acertou a roleta do PicKap esta semana?",
    "Foto do show saiu! Procurem no Photo Finder.",
    "Dica: chegar cedo garante a grade. Aprendi do jeito difícil.",
    "Saudade do show de verão. Quando volta?",
    "Montei uma playlist com os maiores hits, quem quer o link?",
]


def avatar_png(rgb: tuple[int, int, int], size: int = 192) -> bytes:
    """PNG liso com um disco claro no meio (sem depender de Pillow)."""
    r, g, b = rgb
    cx = cy = size / 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d < size * 0.22:
                row += bytes((255, 255, 255))
            elif d < size * 0.30:
                row += bytes((min(255, r + 50), min(255, g + 50), min(255, b + 50)))
            else:
                row += bytes((r, g, b))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


COMMENTS = [
    "Amei!", "Que noite foi essa 🔥", "Tô dentro da caravana!", "Quero muito ir", "Melhor set do ano",
    "Alguém tem foto desse momento?", "Isso aí, galera!", "Chegando cedo eu garanto a grade", "Saudade demais",
    "Boa, vou chamar o pessoal", "Topo o encontro antes do show", "Esse drop não sai da minha cabeça",
]


def photo_png(seed: int, w: int = 288, h: int = 360) -> bytes:
    """Arte abstrata em tons quentes/frios (faixas e um disco), só para ilustrar posts de exemplo."""
    rnd = random.Random(seed)
    hue = rnd.random()
    c1 = [int(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.65, 0.35)]
    c2 = [int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.08) % 1, 0.75, 0.95)]
    c3 = [int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.5) % 1, 0.5, 0.9)]
    cx, cy, rad = rnd.randint(w // 4, 3 * w // 4), rnd.randint(h // 3, 2 * h // 3), rnd.randint(w // 6, w // 3)
    band = rnd.randint(18, 48)
    rows = []
    for y in range(h):
        row = bytearray([0])
        t = y / h
        for x in range(w):
            if (x - cx) ** 2 + (y - cy) ** 2 < rad**2:
                col = c3
            elif ((x + y) // band) % 2 == 0:
                col = [int(c1[i] * (1 - t) + c2[i] * t * 0.55) for i in range(3)]
            else:
                col = [int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)]
            row += bytes(col)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def enrich_posts(db, artist, upload_dir: Path, rnd: random.Random, now: datetime) -> None:
    """Dá comentários e fotos aos posts de exemplo que ainda não têm (pode rodar várias vezes)."""
    commenters = [u for u in db.scalars(select(m.User).where(m.User.role == m.ROLE_FAN))]
    added_c = added_p = 0
    for post in db.scalars(select(m.Post).where(m.Post.artist_id == artist.id)):
        if not post.replies and commenters:
            for _ in range(rnd.randint(1, 5)):
                when = min(now, post.created_at.replace(tzinfo=timezone.utc) + timedelta(hours=rnd.randint(1, 72)))
                db.add(m.PostComment(post=post, author_id=rnd.choice(commenters).id, text=rnd.choice(COMMENTS), created_at=when))
                added_c += 1
            post.comments = max(post.comments, len(post.replies))
        if not post.image_path and post.kind in ("galera", "drop") and rnd.random() < 0.55:
            fname = f"mock-post-{post.id}.png"
            (upload_dir / fname).write_bytes(photo_png(rnd.randint(0, 10_000)))
            post.image_path, post.has_image = f"/uploads/{fname}", True
            added_p += 1
    db.flush()
    print(f"+ {added_c} comentários e {added_p} fotos nos posts")


def main() -> None:
    rnd = random.Random(42)
    now = datetime.now(timezone.utc)
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    pw = hash_password(PASSWORD)

    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST_SLUG))
        if not artist:
            raise SystemExit("O ambiente vintage-culture não existe. Suba a API uma vez para criar o seed.")
        existing = {c.name for c in db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id))}

        for idx, (name, city, uf, (owner_name, owner_email), rgb, desc) in enumerate(CLUBS):
            if name in existing:
                print(f"- {name}: já existe, pulei")
                continue
            club = create_club(db, artist, name, desc, city)
            fname = f"mock-clube-{club.slug}.png"
            (upload_dir / fname).write_bytes(avatar_png(rgb))
            club.avatar_path = f"/uploads/{fname}"

            owner = db.scalar(select(m.User).where(m.User.email == owner_email))
            if not owner:
                owner = m.User(email=owner_email, name=owner_name, password_hash=pw, role=m.ROLE_ARTIST_ADMIN, city=city, state=uf)
                db.add(owner)
                db.flush()
            db.add(m.ClubStaff(club_id=club.id, user_id=owner.id, role=m.STAFF_OWNER, role_label="Dono do fã clube"))

            for p in range(rnd.randint(2, 4)):  # prêmios da roleta
                db.add(m.Prize(artist_id=artist.id, club_id=club.id, label=rnd.choice(["Camiseta", "Boné", "Pôster", "Copo do clube", "+30 pts", "Tente de novo"]), position=p))

            members = []
            for n in range(rnd.randint(9, 24)):
                first, last = rnd.choice(FIRST), rnd.choice(LAST)
                email = f"{first}.{last}.{club.slug}.{n}@exemplo.com".lower().replace("ã", "a").replace("í", "i").replace("é", "e").replace("ó", "o").replace("á", "a")
                u = m.User(
                    email=email, name=f"{first} {last}", handle=f"@{first.lower()}.{last.lower()}", password_hash=pw, role=m.ROLE_FAN,
                    zip_code=f"{rnd.randint(10000, 99999)}-{rnd.randint(100, 999)}", street=rnd.choice(STREETS), number=str(rnd.randint(1, 1500)),
                    neighborhood=rnd.choice(HOODS), city=city if rnd.random() < 0.8 else rnd.choice(["Campinas", "Santos", "Niterói", "Goiânia"]),
                    state=uf,
                )
                db.add(u)
                db.flush()
                joined = now - timedelta(days=rnd.randint(0, 34), hours=rnd.randint(0, 23))
                db.add(m.ClubMember(club_id=club.id, user_id=u.id, created_at=joined))
                status = rnd.choices(["active", "pending", "canceled", None], [5, 1, 1, 3])[0]
                db.add(
                    m.Fandom(
                        artist_id=artist.id, user_id=u.id, luck_points=rnd.randint(0, 200), member_status=status,
                        member_since=(joined.date() if status else None), created_at=joined,
                    )
                )
                members.append((u, joined))

            for _ in range(rnd.randint(6, 12)):
                author, joined = rnd.choice(members)
                when = max(joined, now - timedelta(days=rnd.randint(0, 29), hours=rnd.randint(0, 23)))
                likes = rnd.randint(2, 140)
                db.add(
                    m.Post(
                        artist_id=artist.id, club_id=club.id, kind="galera", author_id=author.id, text=rnd.choice(POSTS),
                        likes=likes, comments=rnd.randint(0, likes // 3), reposts=rnd.randint(0, likes // 6),
                        views=likes * rnd.randint(6, 18), created_at=when,
                    )
                )
            db.flush()
            print(f"+ {name}: dono {owner_email}, {len(members)} membros")
        enrich_posts(db, artist, upload_dir, rnd, now)
        db.commit()


if __name__ == "__main__":
    main()
