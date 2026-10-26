"""Oferece experiências avulsas nos pacotes dos shows que ainda vão acontecer: jantar com o Vintage, meet & greet no
camarim (foto com ele no show), pré-esquenta, after e hotel com hospedagem. O fã escolhe o ingresso e vai marcando as
experiências que quer; o total soma. O Photo Finder já vem em todos os pacotes.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_pacotes_experiencia.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_pacotes_experiencia.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_pacotes_experiencia.py

Pode rodar de novo: só mexe nos pacotes que ainda não têm experiências. Também apaga os pacotes fechados de experiência
(Jantar, Camarim, Pré-esquenta, After, Hotel e Experiência completa) criados numa versão anterior deste script.
"""

from datetime import date

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

ARTIST = "vintage-culture"

# chave, preço extra por pessoa (R$), vagas esgotadas em algum pacote (só para exemplo)
ADDONS = [("jantar", 450), ("camarim", 600), ("pre", 120), ("after", 180), ("hotel", 380)]
OLD_PACKAGES = ("Jantar com o Vintage", "Meet & greet no camarim", "Pré-esquenta", "After oficial", "Hotel com hospedagem", "Experiência completa Vintage")


def main() -> None:
    updated = removed = 0
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        for ev in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id).order_by(m.Event.date)):
            for p in list(ev.packages):
                if p.name.split(" · ")[0] in OLD_PACKAGES:
                    db.delete(p)
                    removed += 1
            db.flush()
            db.refresh(ev)
            if ev.date < date.today():
                continue
            for p in ev.packages:
                if p.addons:
                    continue
                p.addons = [{"key": key, "price_cents": price * 100, "sold_out": key == "camarim" and p.position == 0} for key, price in ADDONS]
                updated += 1
            print(f"+ {ev.city}: {len(ev.packages)} pacotes com experiências")
        db.commit()
    print(f"{updated} pacotes ganharam experiências; {removed} pacotes fechados de experiência apagados")


if __name__ == "__main__":
    main()
