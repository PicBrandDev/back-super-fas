"""Cria o anúncio da Red Bull (uma imagem) na vitrine "Anúncio ao pegar o brinde" (pickup_resgate) de todos os ambientes ativos (Vintage Culture, Departamento, Anitta, Ludmilla e os que vierem).

É a modal que abre depois que o fã ganha na roleta, quando ele toca para pegar o brinde. A imagem já está no bucket
(`/uploads/redbull-pos-brinde.png`). O script cria uma campanha aprovada, valendo de hoje a 30 dias, em cada ambiente. O patrocinador
Red Bull já existe. Não duplica: se a Red Bull já tem campanha nessa vitrine, pula.

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/anuncio_redbull.py
Local:    PYTHONPATH=. python scripts/anuncio_redbull.py
"""

from datetime import date, timedelta

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

BRAND = "Red Bull"
EMAIL = "redbull@patrocinio.example"
ARTE = "/uploads/redbull-pos-brinde.png"
CHAVE = "pickup_resgate"
DIAS = 30

TITULO = "A temporada de festas ficou melhor"
TEXTO = "Comemore o seu brinde com a Red Bull: energia para o set não cair."
BOTAO = "Conhecer a Red Bull"
LINK = "https://www.redbull.com/br-pt"

with SessionLocal() as db:
    sp = db.scalar(select(m.Sponsor).where(m.Sponsor.email == EMAIL))
    if not sp:  # o patrocinador pode existir com outro e-mail (ex.: o do portal); procura pela marca
        sp = db.scalar(select(m.Sponsor).where(m.Sponsor.brand == BRAND).order_by(m.Sponsor.created_at))
    if not sp:
        sp = m.Sponsor(brand=BRAND, email=EMAIL, status="active")
        db.add(sp)
        db.flush()
        print(f"patrocinador {BRAND} criado")
    hoje = date.today()
    for artist in db.scalars(select(m.Artist).where(m.Artist.status == "active").order_by(m.Artist.slug)):
        slug = artist.slug
        slot = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == artist.id, m.AdSlot.key == CHAVE, m.AdSlot.club_id.is_(None)))
        if not slot:
            print(f"{slug}: a vitrine 'Anúncio ao pegar o brinde' não existe (suba a API nova para criar as vitrines)")
            continue
        if db.scalar(select(m.Campaign.id).where(m.Campaign.slot_id == slot.id, m.Campaign.sponsor_id == sp.id)):
            print(f"{slug}: a {BRAND} já tem campanha nesta vitrine, nada a fazer")
            continue
        db.add(
            m.Campaign(
                sponsor_id=sp.id,
                slot_id=slot.id,
                brand=BRAND,
                title=TITULO,
                text=TEXTO,
                cta=BOTAO,
                url=LINK,
                art_path=ARTE,
                start=hoje,
                end=hoje + timedelta(days=DIAS),
                status="approved",
            )
        )
        print(f"{slug}: campanha criada ({hoje:%d/%m} a {hoje + timedelta(days=DIAS):%d/%m}), vitrine {'ligada' if slot.active else 'DESLIGADA (ligue em /admin/midia)'}")
    db.commit()
print("pronto")
