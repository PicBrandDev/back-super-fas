"""Compradores de experiências de teste, para a lista de compradores da tela do show no admin (Agenda > Compra e brindes).

Não se vende mais ingresso pelo app: os pacotes vendem experiências (transfer, jantar, camarim, pré-esquenta, after,
hotel). Para cada show com pacotes, o script:
  1. garante que os pacotes tenham experiências (se não tiverem, põe transfer e as demais com preços de exemplo),
     limpa os ingressos antigos de dentro dos pacotes e renomeia os pacotes de exemplo antigos ("Somente ingresso",
     "Ingresso + transfer"...) para nomes de experiência;
  2. cria compras de experiência de fãs do ambiente (de 25 a 70 por show; cada fã escolhe de 1 a 3 experiências de
     um pacote), espalhadas pelos últimos 30 dias, algumas com cupom.

Pode rodar de novo: pula os shows que já têm 20 ou mais compras de experiência. Não mexe em compras de verdade.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_compradores_experiencias.py
"""

import os
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app import models as m
from app.db import SessionLocal
from app.defaults import ADDON_LABELS

SLUG = os.environ.get("ARTIST", "vintage-culture")
# nomes antigos dos pacotes de exemplo (mock_agencias) -> nome e descrição novos
RENAME = [
    ("Somente ingresso", "Experiências do show", "Jantar, camarim, pré-esquenta, after e hotel: escolha as que quiser."),
    ("Ingresso + transfer + selo", "Transfer + experiências", "Tudo do pacote de experiências mais o ônibus em grupo."),
    ("Ingresso + transfer", "Transfer ida e volta", "Ônibus em grupo, ida e volta, e as experiências que quiser somar."),
]
DEFAULT_ADDONS = [("transfer", 9000), ("jantar", 45000), ("camarim", 60000), ("pre", 12000), ("after", 18000), ("hotel", 38000)]


def main() -> None:
    rnd = random.Random(11)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
        if not artist:
            raise SystemExit(f"ambiente {SLUG} não existe")
        fans = [f.user_id for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id))]
        total = 0
        for ev in db.scalars(select(m.Event).where(m.Event.artist_id == artist.id).order_by(m.Event.date)):
            pkgs = [p for p in ev.packages if p.active]
            if not pkgs:
                continue
            for p in pkgs:
                if not p.addons:
                    p.addons = [{"key": k, "price_cents": cents, "sold_out": False} for k, cents in DEFAULT_ADDONS]
                p.items = []
                for old, new, desc in RENAME:
                    if p.name.startswith(old):
                        p.name, p.description = p.name.replace(old, new, 1), desc
                        break
            have = db.scalar(select(func.count(m.TicketPurchase.id)).where(m.TicketPurchase.event_id == ev.id, m.TicketPurchase.kind == "experience")) or 0
            if have >= 20:
                print(f"- {ev.city}: já tem {have} compras de experiência, pulei")
                continue
            for user_id in rnd.sample(fans, min(rnd.randint(25, 70), len(fans))):
                p = rnd.choice(pkgs)
                offer = [a for a in p.addons if not a.get("sold_out")]
                if not offer:
                    continue
                picked = rnd.sample(offer, min(rnd.choice([1, 1, 2, 3]), len(offer)))
                price = sum(a["price_cents"] for a in picked)
                coupon, off = ("", 0)
                if rnd.random() < 0.15:
                    coupon, off = "VINTAGE10", price // 10
                db.add(
                    m.TicketPurchase(
                        artist_id=artist.id, user_id=user_id, event_id=ev.id, package_name=p.name, agency_name=p.agency.name,
                        label=" + ".join(ADDON_LABELS.get(a["key"], a["key"]) for a in picked), kind="experience",
                        addons=[a["key"] for a in picked], price_cents=price - off, coupon_code=coupon, discount_cents=off,
                        created_at=now - timedelta(days=rnd.random() * 30, hours=rnd.random() * 8),
                    )
                )
                total += 1
            print(f"+ {ev.city}: compras de experiência criadas")
        db.commit()
        print(f"pronto: {total} compras de experiência criadas.")


main()
