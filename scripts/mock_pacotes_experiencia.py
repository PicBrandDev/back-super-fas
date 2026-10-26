"""Cria pacotes de experiência nos shows que ainda vão acontecer: jantar com o Vintage, meet & greet no camarim
(foto com ele no show), pré-esquenta, after e a experiência completa. Todos os pacotes já incluem o Photo Finder.

    PYTHONPATH=. .venv/Scripts/python scripts/mock_pacotes_experiencia.py      # Windows
    PYTHONPATH=. .venv/bin/python scripts/mock_pacotes_experiencia.py          # Linux/Mac

No servidor (a pasta scripts não vai dentro do container):

    sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_pacotes_experiencia.py

Pode rodar de novo: pula o pacote de experiência que o show já tem. Usa a agência dos pacotes do show
(rode antes o mock_agencias.py se o show ainda não tiver agência).
"""

from datetime import date

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal

ARTIST = "vintage-culture"

# chave, nome, descrição, extra por pessoa (R$), vagas limitadas
EXPERIENCES = [
    ("jantar", "Jantar com o Vintage", "Jantar exclusivo com o Vintage Culture horas antes do show, com mesa reservada e menu fechado.", 450),
    ("camarim", "Meet & greet no camarim", "Encontro com o Vintage no camarim e foto com ele no show. Vagas limitadas.", 600),
    ("pre", "Pré-esquenta", "Festa de pré-esquenta com DJs convidados e open bar, até a abertura dos portões.", 120),
    ("after", "After oficial", "After party pós-show com open bar e entrada garantida, na mesma noite.", 180),
]
TYPES = [("Pista", 1.0), ("Pista Premium", 1.6), ("Camarote", 2.4)]


def main() -> None:
    created = 0
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == ARTIST))
        if not artist:
            raise SystemExit(f"O ambiente {ARTIST} não existe.")
        for ev in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id).order_by(m.Event.date)):
            if ev.date < date.today():
                continue
            if not ev.packages:
                print(f"- {ev.city}: sem pacotes/agência, pulei (rode o mock_agencias.py)")
                continue
            agency = ev.packages[0].agency
            if any(p.experiences for p in ev.packages):
                print(f"- {ev.city}: já tem pacotes de experiência, pulei")
                continue
            ticket = {t.label: t.price_cents // 100 for t in ev.tickets}
            base = ticket.get("Pista", 180)
            pos = max((p.position for p in ev.packages), default=-1) + 1

            def price(label: str, mult: float, extra: int) -> int:
                return (ticket.get(label) or int(base * mult)) + extra

            packs = [(key, name, desc, extra, [key]) for key, name, desc, extra in EXPERIENCES]
            packs.append(("completa", "Experiência completa Vintage",
                          "Jantar, meet & greet no camarim com foto, pré-esquenta e after, tudo no mesmo pacote.", 1100, [k for k, *_ in EXPERIENCES]))
            for key, name, desc, extra, exps in packs:
                tipos = TYPES if key in ("pre", "after") else TYPES[1:]  # jantar e camarim só com Pista Premium ou Camarote
                nome = {"jantar": "jantar com o Vintage", "camarim": "meet & greet no camarim", "pre": "pré-esquenta", "after": "after", "completa": "experiência completa"}[key]
                items = [
                    {"kind": "ticket", "label": f"{label} + {nome}", "price_cents": price(label, mult, extra) * 100, "sold_out": False}
                    for label, mult in tipos
                ]
                db.add(
                    m.EventPackage(
                        artist_id=artist.id, event_id=ev.id, agency_id=agency.id, name=f"{name} · {ev.city}", description=desc,
                        url=f"{agency.url}/vintage-culture/experiencia-{key}", items=items, experiences=exps, position=pos,
                    )
                )
                pos += 1
                created += 1
            print(f"+ {ev.city}: {len(packs)} pacotes de experiência")
        db.commit()
    print(f"{created} pacotes de experiência criados")


if __name__ == "__main__":
    main()
