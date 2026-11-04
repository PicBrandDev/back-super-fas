"""Cria o anúncio em vídeo da Coca-Cola na vitrine "Vídeo antes do giro" (pickup_video) do Vintage Culture e do Departamento.

O vídeo já está no bucket (`/uploads/coca-cola-antes-do-giro.mp4`). Este script cria o patrocinador Coca-Cola (se não existir)
e uma campanha aprovada, valendo de hoje a 30 dias, em cada ambiente. Não duplica: se a Coca já tem campanha nessa vitrine, pula.

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/anuncio_coca.py
Local:    PYTHONPATH=. python scripts/anuncio_coca.py
"""

from datetime import date, timedelta

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

BRAND = "Coca-Cola"
EMAIL = "cocacola@patrocinio.example"
VIDEO = "/uploads/coca-cola-antes-do-giro.mp4"
AMBIENTES = ["vintage-culture", "departamento"]
DIAS = 30

TITULO = "Abra a felicidade no set"
TEXTO = "Coca-Cola geladinha em cada show do Vintage Culture."
BOTAO = "Quero uma Coca"
LINK = "https://www.coca-cola.com/br/pt"

with SessionLocal() as db:
    sp = db.scalar(select(m.Sponsor).where(m.Sponsor.email == EMAIL))
    if not sp:
        sp = m.Sponsor(brand=BRAND, email=EMAIL, status="active")
        db.add(sp)
        db.flush()
        print(f"patrocinador {BRAND} criado")
    hoje = date.today()
    for slug in AMBIENTES:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == slug))
        if not artist:
            print(f"{slug}: ambiente não encontrado")
            continue
        slot = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == artist.id, m.AdSlot.key == "pickup_video", m.AdSlot.club_id.is_(None)))
        if not slot:
            print(f"{slug}: a vitrine 'Vídeo antes do giro' não existe (suba a API nova para criar as vitrines)")
            continue
        if db.scalar(select(m.Campaign.id).where(m.Campaign.slot_id == slot.id, m.Campaign.sponsor_id == sp.id)):
            print(f"{slug}: a Coca-Cola já tem campanha nesta vitrine, nada a fazer")
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
                video_url=VIDEO,
                start=hoje,
                end=hoje + timedelta(days=DIAS),
                status="approved",
            )
        )
        print(f"{slug}: campanha criada ({hoje:%d/%m} a {hoje + timedelta(days=DIAS):%d/%m}), vitrine {'ligada' if slot.active else 'DESLIGADA (ligue em /admin/midia)'}")
    db.commit()
print("pronto")
