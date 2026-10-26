"""Cria anúncios de exemplo, aprovados e no ar, nas 4 vitrines dentro do app do vintage-culture
(o que o fã recebe em GET /artists/vintage-culture/ads/in-app):

    entrada         -> entry        Festival Maré (festival / ingressos)
    pickup_video    -> pickupVideo  Departamento (vídeo vertical do lançamento Toxic, com o Vintage Culture)
    pickup_resgate  -> pickupClaim  Onda (conta digital, fictícia)
    mural           -> feed         Spotify (post discreto chamando para ouvir o artista)

São marcas de fora (nada da loja ou do artista), com as artes e o vídeo que estão no front em
/public/ads/ (o caminho "/ads/..." é servido pelo próprio front). Em produção, o patrocinador envia
o vídeo pelo portal (upload ou link http/https).

    PYTHONPATH=. .venv/Scripts/python scripts/mock_anuncios_app.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_anuncios_app.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_anuncios_app.py

Pode rodar de novo: não duplica (procura pelo título) e só atualiza os textos, a arte, o vídeo e as datas.
Antes, aplica as migrações (coluna video_url e vitrines novas), igual à subida da API.
"""

from datetime import date, timedelta

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal, engine
from app.migrations import upgrade

VIDEO_URL = "/ads/toxic-departamento.mp4"  # servido pelo front (public/ads); em produção, um link http(s) ou upload

# (vitrine, marca, e-mail do patrocinador, título, texto, cta, link, arte, vídeo)
ADS = [
    (
        "entrada", "Festival Maré", "mare@patrocinio.example", "Lote 1 do Festival Maré no ar",
        "3 dias de praia e pista. Fã clube tem pré-venda com 15% off.", "Garantir ingresso",
        "https://example.com/mare", "/ads/exemplo-mare.svg", "",
    ),
    (
        "pickup_video", "Departamento", "departamento@patrocinio.example", "Toxic: Vintage Culture x Departamento",
        "Três anos de estúdio e finalmente saiu. Assista e libere o seu giro.", "Ouvir agora",
        "https://open.spotify.com/search/Vintage%20Culture%20Departamento%20Toxic", "/ads/toxic-departamento.jpg", VIDEO_URL,
    ),
    (
        "pickup_resgate", "Onda", "onda@patrocinio.example", "Ganhou? Guarde o prêmio na Onda",
        "Conta digital com cartão sem anuidade, Pix na hora e cashback em ingressos.", "Abrir minha conta",
        "https://example.com/onda", "/ads/exemplo-onda.svg", "",
    ),
    (
        "mural", "Spotify", "spotify@patrocinio.example", "Vintage Culture no Spotify",
        "Os sets e lançamentos no seu app de música.", "Ouvir",
        "https://open.spotify.com/search/Vintage%20Culture", "/ads/spotify.jpg", "",
    ),
]

RETIRED = [
    ("pickup_video", "pulso@patrocinio.example"), ("pickup_video", "djmag@patrocinio.example"),
    ("mural", "sinal@patrocinio.example"),
]


def main() -> None:
    upgrade(engine)
    today = date.today()
    start, end = today - timedelta(days=2), today + timedelta(days=60)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        if not artist:
            raise SystemExit("O ambiente vintage-culture não existe.")
        added = updated = 0
        for key, brand, email, title, text, cta, url, art, video in ADS:
            slot = db.scalar(
                select(m.AdSlot).where(m.AdSlot.artist_id == artist.id, m.AdSlot.club_id.is_(None), m.AdSlot.key == key)
            )
            if not slot:
                raise SystemExit(f"A vitrine {key} não existe.")
            if not slot.active:
                print(f"! a vitrine {key} está desligada: o anúncio só aparece quando ela for ligada")
            sp = db.scalar(select(m.Sponsor).where(m.Sponsor.email == email))
            if not sp:
                sp = m.Sponsor(brand=brand, email=email, status="active")
                db.add(sp)
                db.flush()
            c = db.scalar(select(m.Campaign).where(m.Campaign.slot_id == slot.id, m.Campaign.title == title))
            if not c:
                c = m.Campaign(sponsor_id=sp.id, slot_id=slot.id, title=title)
                db.add(c)
                added += 1
            else:
                updated += 1
            c.brand, c.text, c.cta, c.url, c.art_path, c.video_url = brand, text, cta, url, art, video
            c.start, c.end, c.status = start, end, "approved"
        # Exemplos antigos que estas marcas substituíram (senão o mais antigo continuaria no ar).
        for key, email in RETIRED:
            for c in db.scalars(
                select(m.Campaign)
                .join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id)
                .join(m.Sponsor, m.Campaign.sponsor_id == m.Sponsor.id)
                .where(m.AdSlot.artist_id == artist.id, m.AdSlot.key == key, m.Sponsor.email == email)
            ):
                db.delete(c)
        db.commit()
        print(f"+ {added} anúncios do app criados, {updated} atualizados (no ar até {end:%d/%m/%Y})")
        if not VIDEO_URL:
            print("  sem vídeo: o front mostra a arte com a contagem de 30 s")


if __name__ == "__main__":
    main()
