"""Anúncios de exemplo da Ludmilla: as marcas da vitrine (Coca-Cola, Sprite, Nike, Spotify, Red Bull, Heineken, Adidas) nos feeds
(Mural, fã clubes e notícias), como já estão na Anitta, para o banner de patrocínio a cada 2 posts alternar entre as marcas.

Faz três coisas, só no ambiente "ludmilla" (não mexe nas campanhas dos outros ambientes):
  1. cria a campanha de cada marca em cada vitrine (pula a que já existe: mesma vitrine, marca e título);
  2. liga a cada campanha a arte da marca que está em public/patrocinadores do front (as artes se revezam entre as campanhas da marca);
  3. escreve visualizações e cliques por dia (de exemplo) para a aba Desempenho do admin não ficar zerada.

Pode rodar de novo. Precisa do ambiente (criar_ludmilla.py) e dos patrocinadores das marcas já no banco.

Local:    PYTHONPATH=. python scripts/anuncios_ludmilla.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/anuncios_ludmilla.py
"""

import random
from datetime import date, timedelta

from sqlalchemy import delete, select

from app import models as m
from app.db import Base, SessionLocal, engine

SLUG = "ludmilla"
VITRINES = ["feed_clubes", "mural", "noticias"]
COPY = {
    "Coca-Cola": ("Abra a felicidade no próximo show", "Gelada na pista, sempre. Resgate a sua com o código SUPERFA.", "Ver oferta", "https://www.cocacola.com.br"),
    "Sprite": ("Refresque o set inteiro", "Bem gelada entre um drop e outro. Cupom SPRITEFA na loja do evento.", "Quero a minha", "https://www.sprite.com.br"),
    "Nike": ("Pisa firme na pista", "A nova coleção para dançar a noite toda. Frete grátis para fã clube.", "Conhecer", "https://www.nike.com.br"),
    "Spotify": ("O set completo está no Spotify", "Ouça Bi Festinha e as prévias do Drops Hits na playlist oficial.", "Ouvir agora", "https://open.spotify.com"),
    "Red Bull": ("Pronto para a madrugada?", "Energia até o último drop. Passe no estande do show.", "Saiba mais", "https://www.redbull.com"),
    "Heineken": ("Um brinde ao próximo show", "Retire o seu brinde no bar oficial com o código do PicKup.", "Ver brinde", "https://www.heineken.com"),
    "Adidas": ("Edição limitada do tour", "Camiseta e boné exclusivos para quem é do fã clube.", "Ver coleção", "https://www.adidas.com.br"),
}
ARTES = {
    "Heineken": ["/patrocinadores/anuncio1.png", "/patrocinadores/anuncio2.png", "/patrocinadores/anuncio3.png"],
    "Nike": [f"/patrocinadores/nike_anuncio{i}.png" for i in range(1, 7)],
    "Sprite": [f"/patrocinadores/sprite_anuncio{i}.png" for i in range(1, 4)],
    "Coca-Cola": ["/patrocinadores/coca_anuncio1.png"],
    "Red Bull": ["/patrocinadores/redbull_anuncio1.png"],
    "Adidas": [f"/patrocinadores/adidas_anuncio{i}.png" for i in range(1, 4)],
    "Spotify": ["/ads/spotify.jpg"],
}

Base.metadata.create_all(engine)  # garante a tabela ad_stats
hoje = date.today()
with SessionLocal() as db:
    art = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
    if not art:
        raise SystemExit("Ambiente ludmilla não encontrado: rode antes o criar_ludmilla.py.")
    slots = {s.key: s for s in art.ad_slots if s.club_id is None}

    # 1. campanhas
    novos = 0
    for marca, (titulo, texto, cta, url) in COPY.items():
        sp = db.scalar(select(m.Sponsor).where(m.Sponsor.brand == marca))
        if not sp:
            print(f"patrocinador {marca} não existe, pulei")
            continue
        for chave in VITRINES:
            slot = slots.get(chave)
            if not slot:
                continue
            if db.scalar(select(m.Campaign.id).where(m.Campaign.slot_id == slot.id, m.Campaign.sponsor_id == sp.id, m.Campaign.title == titulo)):
                continue
            db.add(m.Campaign(sponsor_id=sp.id, slot_id=slot.id, brand=marca, title=titulo, text=texto, cta=cta, url=url,
                              start=hoje - timedelta(days=3), end=hoje + timedelta(days=25), status="approved"))
            novos += 1
    db.flush()
    print(f"campanhas novas: {novos}")

    # 2. artes (só as campanhas da Ludmilla; vídeo mantém a capa)
    camps = list(db.scalars(select(m.Campaign).join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id).where(m.AdSlot.artist_id == art.id).order_by(m.Campaign.created_at, m.Campaign.id)))
    por_marca: dict[str, int] = {}
    for c in camps:
        if c.video_url or c.brand not in ARTES:
            continue
        i = por_marca.get(c.brand, 0)
        por_marca[c.brand] = i + 1
        c.art_path = ARTES[c.brand][i % len(ARTES[c.brand])]

    # 3. desempenho (mesma fórmula do mock_desempenho_anuncios.py, só nas campanhas aprovadas da Ludmilla)
    n = 0
    for c in camps:
        if c.status != "approved":
            continue
        rnd = random.Random(c.id)
        first = max(c.start or hoje - timedelta(days=60), hoje - timedelta(days=60))
        last = min(c.end or hoje, hoje)
        db.execute(delete(m.AdStat).where(m.AdStat.campaign_id == c.id))
        base = rnd.randint(150, 1400)
        ctr = rnd.uniform(0.012, 0.06)
        d = first
        while d <= last:
            wave = 1 + 0.35 * ((d.weekday() >= 4) - 0.5)  # sexta a domingo rende mais
            views = max(0, int(base * wave * rnd.uniform(0.7, 1.3)))
            clicks = int(views * ctr * rnd.uniform(0.7, 1.3))
            db.add(m.AdStat(campaign_id=c.id, day=d, views=views, clicks=clicks))
            n += 1
            d += timedelta(days=1)
    db.commit()
    print(f"{len(camps)} campanhas da Ludmilla com arte; {n} dias de números de desempenho")
