"""Cria uma campanha de exemplo da Coca-Cola, no ar, para a conta patrocinador@fapage.com.br
(a que aparece em "Minhas campanhas" do portal do patrocinador).

    PYTHONPATH=. .venv/Scripts/python scripts/mock_campanha_cocacola.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_campanha_cocacola.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_campanha_cocacola.py

Pode rodar de novo: não duplica a campanha.
"""

import shutil
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.db import SessionLocal
from app.models import new_id

EMAIL = "patrocinador@fapage.com.br"
TITLE = "Abra a felicidade no próximo show"
ART = Path(__file__).resolve().parents[2] / "front-super-fas" / "public" / "ads" / "coca-cola.png"


def save_art() -> str:
    """Copia a arte de exemplo para a pasta de uploads (se o arquivo estiver ao lado deste repositório)."""
    if not ART.exists():
        return ""
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{new_id()}.png"
    shutil.copy(ART, folder / name)
    return f"/uploads/{name}"


def main() -> None:
    with SessionLocal() as db:
        sponsor = db.scalar(select(m.Sponsor).where(m.Sponsor.email == EMAIL))
        if not sponsor:
            raise SystemExit(f"O patrocinador {EMAIL} não existe. Rode scripts/contas_vintage.py antes.")
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == "vintage-culture"))
        if not artist:
            raise SystemExit("O ambiente vintage-culture não existe.")
        slot = db.scalar(
            select(m.AdSlot).where(m.AdSlot.artist_id == artist.id, m.AdSlot.club_id.is_(None), m.AdSlot.key == "home")
        )
        if not slot:
            raise SystemExit("A vitrine da Home do ambiente não existe.")
        old = db.scalar(select(m.Campaign).where(m.Campaign.sponsor_id == sponsor.id, m.Campaign.title == TITLE))
        if old:
            old.target_city, old.target_radius_km, old.goal_views, old.goal_clicks, old.budget_cents = "São Paulo, SP", 100, 40000, 1200, 312000
            old.art_path = old.art_path or save_art()
            db.commit()
            print("Campanha da Coca-Cola atualizada.")
            return
        today = date.today()
        db.add(
            m.Campaign(
                sponsor_id=sponsor.id,
                slot_id=slot.id,
                brand="Coca-Cola",
                title=TITLE,
                text="Gelada na pista, sempre. Resgate sua Coca-Cola grátis com o código SUPERFA.",
                cta="Ver oferta",
                target_city="São Paulo, SP",
                target_radius_km=100,
                goal_views=40000,
                goal_clicks=1200,
                budget_cents=312000,
                url="https://www.cocacola.com.br",
                start=today - timedelta(days=6),
                end=today + timedelta(days=21),
                art_path=save_art(),
                status="approved",
            )
        )
        db.commit()
        print("+ campanha da Coca-Cola criada")


if __name__ == "__main__":
    main()
