"""Põe todas as marcas de exemplo nos feeds (Mural, fã clubes e notícias) de Vintage Culture, Departamento e Anitta, para o banner
de patrocínio a cada 2 posts alternar entre Coca-Cola, Sprite, Nike, Spotify, Red Bull, Heineken e Adidas.

Pula a campanha que já existe (mesma vitrine, marca e título). As artes que o projeto já tem vão junto; nas outras marcas
o banner sai só com título e texto (use scripts/artes_public.py para ligar as artes certas depois).

Local:    PYTHONPATH=. python scripts/mock_feed_marcas.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_feed_marcas.py
"""

from datetime import date, timedelta

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

ARTISTAS = ["vintage-culture", "departamento", "anitta"]
VITRINES = ["feed_clubes", "mural", "noticias"]
ARTE = {"Coca-Cola": "/patrocinadores/coca_anuncio1.png", "Spotify": "/ads/spotify.jpg"}
COPY = {
    "Coca-Cola": ("Abra a felicidade no próximo show", "Gelada na pista, sempre. Resgate a sua com o código SUPERFA.", "Ver oferta", "https://www.cocacola.com.br"),
    "Sprite": ("Refresque o set inteiro", "Bem gelada entre um drop e outro. Cupom SPRITEFA na loja do evento.", "Quero a minha", "https://www.sprite.com.br"),
    "Nike": ("Pisa firme na pista", "A nova coleção para dançar a noite toda. Frete grátis para fã clube.", "Conhecer", "https://www.nike.com.br"),
    "Spotify": ("O set completo está no Spotify", "Ouça as prévias do Drops Hits na playlist oficial.", "Ouvir agora", "https://open.spotify.com"),
    "Red Bull": ("Pronto para a madrugada?", "Energia até o último drop. Passe no estande do show.", "Saiba mais", "https://www.redbull.com"),
    "Heineken": ("Um brinde ao próximo show", "Retire o seu brinde no bar oficial com o código do PicKup.", "Ver brinde", "https://www.heineken.com"),
    "Adidas": ("Edição limitada do tour", "Camiseta e boné exclusivos para quem é do fã clube.", "Ver coleção", "https://www.adidas.com.br"),
}

hoje = date.today()
with SessionLocal() as db:
    novos = 0
    for slug in ARTISTAS:
        art = db.scalar(select(m.Artist).where(m.Artist.slug == slug))
        if not art:
            print(f"{slug}: não existe, pulei")
            continue
        slots = {s.key: s for s in art.ad_slots if s.club_id is None}
        for marca, (titulo, texto, cta, url) in COPY.items():
            sp = db.scalar(select(m.Sponsor).where(m.Sponsor.brand == marca))
            if not sp:
                continue
            for chave in VITRINES:
                slot = slots.get(chave)
                if not slot:
                    continue
                if db.scalar(select(m.Campaign.id).where(m.Campaign.slot_id == slot.id, m.Campaign.sponsor_id == sp.id, m.Campaign.title == titulo)):
                    continue
                db.add(m.Campaign(sponsor_id=sp.id, slot_id=slot.id, brand=marca, title=titulo, text=texto, cta=cta, url=url,
                                  art_path=ARTE.get(marca, ""), start=hoje - timedelta(days=3), end=hoje + timedelta(days=25), status="approved"))
                novos += 1
    db.commit()
    print(f"{novos} campanhas novas nos feeds")
