"""Enche o feed da Comunidade com posts de exemplo: posts do fã clube oficial do Vintage Culture (com o selo oficial),
posts dos donos de cada fã clube (com o selo de dono), posts dos fãs, fotos, curtidas e comentários.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_feed.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_feed.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_feed.py

Pode rodar de novo: pula os posts que já existem (mesmo fã clube e mesmo texto).
"""

import colorsys
import random
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal

ARTIST = "vintage-culture"

OFFICIAL = [
    "Fanzone no ar! Prévias exclusivas, roleta do PicKup e fotos oficiais dos shows, tudo num lugar só.",
    "Próxima parada: São Paulo, 07 de novembro. Pacotes com transfer e selo no app já estão à venda.",
    "Obrigado, Campinas! Vocês fizeram uma noite que a gente vai lembrar por muito tempo.",
    "Drop novo na área: Faixa inédita 01 já está no Drops Hits. Quem ouvir primeiro conta aqui o que achou.",
    "Quem postou com a #EuSouUmSuperFaDoVintage esta semana subiu no ranking Fã Super. Confiram a lista.",
    "Fotos oficiais do show de Campinas liberadas. Mande uma selfie no Photo Finder e encontre as suas.",
    "A roleta do PicKup tem prêmio novo: camiseta Tour 2026. Quem ganhar mostra aqui!",
    "Bastidores da turnê: soundcheck, estrada e muita história. Em breve, mais aqui no mural.",
    "Lembrete: o transfer de cada pacote sai 4 horas antes do show. Confirmem o ponto de encontro com a agência.",
    "Vocês são o melhor público do Brasil. Sem exagero.",
]

OWNER = [
    "Caravana {city}: lista aberta! Quem quer ir no próximo show do Vintage comenta aqui.",
    "Pré-balada do {club} neste sábado, às 19h. Vai ter set de abertura e troca de camisetas.",
    "Sorteio da semana: ingresso duplo para quem postar a foto do show com #EuSouUmSuperFaDoVintage.",
    "Resumo do encontro de ontem: muita gente, três DJs e um pôr do sol que ninguém esquece.",
    "Atenção, galera de {city}: o transfer sai 4 horas antes do show. Confirmem presença nos comentários.",
    "Bem-vindos aos novos membros! Mandem uma foto de vocês e contem qual foi o primeiro show.",
    "Dica do dono: o Drops Hits liberou prévia nova. Corre ouvir e conta aqui o que achou.",
    "Foto da semana! Quem aparece aí marca os amigos.",
]

FANS = [
    "Quem vai no próximo show? Bora combinar a caravana!",
    "Fui no show de ontem e ainda estou sem voz. Que noite!",
    "Alguém tem a lista de faixas do último set? Preciso rever.",
    "Vamos fazer um encontro antes do show? Sugestões de bar?",
    "Esse drop novo é o melhor do ano, não aceito discussão.",
    "Quem acertou a roleta do PicKup esta semana?",
    "Dica: chegar cedo garante a grade. Aprendi do jeito difícil.",
    "Montei uma playlist com os maiores hits, quem quer o link?",
]

COMMENTS = [
    "Amei!", "Que noite foi essa 🔥", "Tô dentro da caravana!", "Quero muito ir", "Melhor set do ano",
    "Alguém tem foto desse momento?", "Isso aí, galera!", "Chegando cedo eu garanto a grade", "Saudade demais",
    "Boa, vou chamar o pessoal", "Topo o encontro antes do show", "Esse drop não sai da minha cabeça",
]


def photo_png(seed: int, w: int = 288, h: int = 360) -> bytes:
    """Arte abstrata em tons quentes e frios (faixas e um disco), só para ilustrar posts de exemplo."""
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

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return bytes([137]) + b"PNG" + bytes([13, 10, 26, 10]) + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b"")


def main() -> None:
    rnd = random.Random(23)
    now = datetime.now(timezone.utc)
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        clubs = list(db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id)))
        fans = list(db.scalars(select(m.User).where(m.User.role == m.ROLE_FAN)))
        added = {"oficial": 0, "donos": 0, "fãs": 0}
        new_posts: list[m.Post] = []

        def add(club, author, text, kind, days_ago, official=False, with_photo=False):
            if db.scalar(select(m.Post).where(m.Post.club_id == club.id, m.Post.text == text)):
                return
            likes = rnd.randint(25, 240) if official or kind == "owner" else rnd.randint(2, 90)
            post = m.Post(
                artist_id=artist.id, club_id=club.id, kind="galera", author_id=author.id if author else None, official=official, text=text,
                likes=likes, comments=0, reposts=rnd.randint(0, max(1, likes // 5)), views=likes * rnd.randint(8, 20),
                created_at=now - timedelta(days=days_ago, hours=rnd.randint(0, 20), minutes=rnd.randint(0, 59)),
            )
            if with_photo:
                db.add(post)
                db.flush()
                name = f"mock-feed-{post.id}.png"
                (folder / name).write_bytes(photo_png(rnd.randint(0, 100_000)))
                post.image_path, post.has_image = f"/uploads/{name}", True
            db.add(post)
            new_posts.append(post)
            added["oficial" if official else ("donos" if kind == "owner" else "fãs")] += 1

        for club in clubs:
            owner = next((st.user for st in club.staff if st.role == m.STAFF_OWNER), None)
            members = [mb.user for mb in club.members if mb.user and mb.user.role == m.ROLE_FAN] or fans
            if club.is_master:
                if owner:
                    for i, text in enumerate(OFFICIAL):
                        add(club, owner, text, "owner", 1 + i * 2, official=True, with_photo=(i % 2 == 0))
            elif owner:
                city = club.city or "sua cidade"
                for i, text in enumerate(OWNER):
                    add(club, owner, text.format(city=city, club=club.name), "owner", 1 + i * 3, with_photo=(i % 3 == 0))
            for i, text in enumerate(rnd.sample(FANS, 4)):
                if members:
                    add(club, rnd.choice(members), text, "fan", rnd.randint(0, 25), with_photo=(i == 0))
        db.flush()

        n_comments = 0
        for post in new_posts:
            if not fans:
                break
            for _ in range(rnd.randint(2, 6)):
                when = min(now, post.created_at.replace(tzinfo=timezone.utc) + timedelta(hours=rnd.randint(1, 60)))
                db.add(m.PostComment(post=post, author_id=rnd.choice(fans).id, text=rnd.choice(COMMENTS), created_at=when))
                n_comments += 1
            post.comments = len(post.replies)
        db.commit()
    print(f"+ {added['oficial']} posts oficiais, {added['donos']} posts de donos, {added['fãs']} posts de fãs e {n_comments} comentários")


if __name__ == "__main__":
    main()
