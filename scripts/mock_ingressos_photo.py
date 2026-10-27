"""Dá a todo usuário do ambiente Vintage Culture um ingresso com o pacote que inclui o Photo Finder, nos shows que já
aconteceram. O ingresso aparece em "Meus ingressos" da Agenda e libera a busca por selfie no Photo Finder.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_ingressos_photo.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_ingressos_photo.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_ingressos_photo.py

Pode rodar de novo: pula quem já tem o ingresso com Photo Finder daquele show. Contas de admin master e de patrocinador não entram.
"""

from datetime import date

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.defaults import ADDON_LABELS

ARTIST = "vintage-culture"
FALLBACK = ("Transfer ida e volta", "Caravana Vintage", 9000)


def main() -> None:
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        events = [e for e in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id)) if e.date < date.today()]
        if not events:
            raise SystemExit("Não há show que já aconteceu: o Photo Finder só abre depois do show.")
        users = list(db.scalars(select(m.User).where(m.User.role.in_([m.ROLE_FAN, m.ROLE_ARTIST_ADMIN]))))

        # entra no ambiente quem ainda não entrou (donos e admin do ambiente também compram ingresso)
        entered = 0
        for u in users:
            if not db.scalar(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == u.id)):
                db.add(m.Fandom(artist_id=artist.id, user_id=u.id))
                entered += 1

        added = 0
        for ev in events:
            label, agency, price = FALLBACK
            pkg_name = "Pacote com Photo Finder"
            for pkg in db.scalars(select(m.EventPackage).where(m.EventPackage.event_id == ev.id)):
                offer = next(iter(pkg.addons or []), None)
                if offer:
                    label, price = ADDON_LABELS.get(offer["key"], offer["key"]), int(offer.get("price_cents", price))
                    agency, pkg_name, addons = pkg.agency.name, pkg.name, [offer["key"]]
                    break
            else:
                addons = ["transfer"]
            for u in users:
                if db.scalar(select(m.TicketPurchase).where(m.TicketPurchase.user_id == u.id, m.TicketPurchase.event_id == ev.id)):
                    continue
                db.add(
                    m.TicketPurchase(
                        artist_id=artist.id, user_id=u.id, event_id=ev.id, package_name=pkg_name, agency_name=agency,
                        label=label, kind="experience", addons=addons, price_cents=price,
                    )
                )
                added += 1
        db.commit()
    print(f"+ {added} ingressos com Photo Finder para {len(users)} usuários em {len(events)} show(s) que já aconteceram ({entered} entraram no ambiente)")


if __name__ == "__main__":
    main()
