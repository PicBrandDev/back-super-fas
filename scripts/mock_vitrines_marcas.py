"""Vitrines alugadas de exemplo com marcas conhecidas (Coca-Cola, Sprite, Nike, Spotify, Red Bull, Heineken, Adidas)
em todas as posições do app: entrada, vídeo antes do giro, modal depois do prêmio, fatia da roleta e os feeds do
Vintage e de cada fã clube. Só para a demonstração das telas de vitrines do admin e do patrocinador.

Só usa as artes que o projeto já tem (Coca-Cola e Spotify, em public/ads do front); nas outras marcas a tela desenha o
banner com a cor da marca, sem logo. Os textos são de exemplo, escritos para a demonstração.

As vitrines da roleta (vídeo antes do giro, anúncio depois do prêmio e fatia patrocinada) ficam todas LIVRES: o app
ainda não tem a roleta com marcas. Se uma rodada anterior deste script reservou alguma delas, ele apaga essas reservas
(só as das marcas de exemplo daqui; campanhas de verdade, como o vídeo do Departamento, não são tocadas).

Pode rodar de novo: pula as campanhas que já existem (mesma vitrine, marca e título).

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_vitrines_marcas.py
"""

import os
from datetime import date, timedelta

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

SLUG = os.environ.get("ARTIST", "vintage-culture")

# marca -> (e-mail do patrocinador, arte que já existe ou "")
BRANDS = {
    "Coca-Cola": ("cocacola@patrocinio.example", "/ads/coca-cola.png"),
    "Sprite": ("sprite@patrocinio.example", ""),
    "Nike": ("nike@patrocinio.example", ""),
    "Spotify": ("spotify@patrocinio.example", "/ads/spotify.jpg"),
    "Red Bull": ("redbull@patrocinio.example", ""),
    "Heineken": ("heineken@patrocinio.example", ""),
    "Adidas": ("adidas@patrocinio.example", ""),
}

# título, texto, botão, link
COPY = {
    "Coca-Cola": ("Abra a felicidade no próximo show", "Gelada na pista, sempre. Resgate a sua com o código SUPERFA.", "Ver oferta", "https://www.cocacola.com.br"),
    "Sprite": ("Refresque o set inteiro", "Bem gelada entre um drop e outro. Cupom SPRITEFA na loja do evento.", "Quero a minha", "https://www.sprite.com.br"),
    "Nike": ("Pisa firme na pista", "A nova coleção para dançar a noite toda. Frete grátis para fã clube.", "Conhecer", "https://www.nike.com.br"),
    "Spotify": ("O set completo está no Spotify", "Ouça as prévias do Drops Hits na playlist oficial.", "Ouvir agora", "https://open.spotify.com"),
    "Red Bull": ("Pronto para a madrugada?", "Energia até o último drop. Passe no estande do show.", "Saiba mais", "https://www.redbull.com"),
    "Heineken": ("Um brinde ao próximo show", "Retire o seu brinde no bar oficial com o código do PicKup.", "Ver brinde", "https://www.heineken.com"),
    "Adidas": ("Edição limitada do tour", "Camiseta e boné exclusivos para quem é do fã clube.", "Ver coleção", "https://www.adidas.com.br"),
}

# (chave da vitrine do ambiente, marca no ar, marca agendada)
ENV_PLAN = [
    ("entrada", "Coca-Cola", "Nike"),
    ("mural", "Spotify", None),  # 1ª posição do feed: o primeiro anúncio que o fã vê
    ("feed_2", "Nike", None),
    ("feed_3", None, "Adidas"),
    ("home", "Coca-Cola", None),
]
# (sufixo da vitrine do clube, marcas por clube na ordem dos clubes)
CLUB_BRANDS = ["Spotify", "Sprite", "Coca-Cola", "Nike", "Red Bull", "Heineken"]
ROLETA_KEYS = {"pickup_video", "pickup_resgate", "pickup"}
PRICE = {"entrada": 150000, "pickup_video": 220000, "pickup_resgate": 120000, "pickup": 90000, "mural": 80000, "feed_2": 70000, "feed_3": 60000, "feed_4": 50000, "home": 100000}


def main() -> None:
    today = date.today()
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
        if not artist:
            raise SystemExit(f"ambiente {SLUG} não existe")
        sponsors: dict[str, m.Sponsor] = {}
        for brand, (email, _) in BRANDS.items():
            sp = db.scalar(select(m.Sponsor).where(m.Sponsor.email == email))
            if not sp:
                sp = m.Sponsor(brand=brand, email=email, status="active")
                db.add(sp)
                db.flush()
            sponsors[brand] = sp
        slots = {s.key: s for s in artist.ad_slots}
        # Roleta sempre livre: apaga o que este script reservou lá numa rodada anterior.
        mine = [sp.id for sp in sponsors.values()]
        roleta_ids = [s.id for k, s in slots.items() if k.split(".", 1)[-1] in ROLETA_KEYS]
        freed = 0
        if roleta_ids:
            for c in db.scalars(select(m.Campaign).where(m.Campaign.slot_id.in_(roleta_ids), m.Campaign.sponsor_id.in_(mine))):
                db.delete(c)
                freed += 1
        for key, s in slots.items():  # preço por semana nas vitrines que ainda não têm
            base = key.split(".", 1)[-1]
            if s.price_cents is None:
                s.price_cents = PRICE.get(base, 60000)

        added = 0

        def book(slot_key: str, brand: str, scheduled: bool, offset: int = 0) -> None:
            nonlocal added
            slot = slots.get(slot_key)
            if not slot:
                return
            title, text, cta, url = COPY[brand]
            sp = sponsors[brand]
            if db.scalar(select(m.Campaign.id).where(m.Campaign.slot_id == slot.id, m.Campaign.sponsor_id == sp.id, m.Campaign.title == title)):
                return
            start = today + timedelta(days=(8 + offset) if scheduled else -(4 + offset))
            db.add(
                m.Campaign(
                    sponsor_id=sp.id, slot_id=slot.id, brand=brand, title=title, text=text, cta=cta, url=url, art_path=BRANDS[brand][1],
                    start=start, end=start + timedelta(days=20), status="approved",
                )
            )
            added += 1

        # Marca trocada de lugar no plano: tira as reservas antigas das marcas de exemplo que não são mais as do plano.
        for key, live, nxt in ENV_PLAN:
            slot = slots.get(key)
            if not slot:
                continue
            for c in db.scalars(select(m.Campaign).where(m.Campaign.slot_id == slot.id, m.Campaign.sponsor_id.in_(mine))):
                if c.brand not in (live, nxt):
                    db.delete(c)
        db.flush()
        for key, live, nxt in ENV_PLAN:
            if live:
                book(key, live, False)
            if nxt:
                book(key, nxt, True)
        clubs = sorted((c for c in artist.clubs if c.status == "active"), key=lambda c: (not c.is_master, c.position))
        for i, c in enumerate(clubs):
            book(f"{c.slug}.mural", CLUB_BRANDS[i % len(CLUB_BRANDS)], False, i)
            if i % 2 == 0:
                book(f"{c.slug}.feed_2", CLUB_BRANDS[(i + 3) % len(CLUB_BRANDS)], False, i)
            if i % 3 == 0:
                book(f"{c.slug}.home", CLUB_BRANDS[(i + 1) % len(CLUB_BRANDS)], True, i)
        db.commit()
        print(f"pronto: {added} aluguéis de vitrine com marcas conhecidas ({len(BRANDS)} marcas); roleta livre ({freed} reservas antigas apagadas).")


main()
