"""Remove do banco as vitrines que saíram do catálogo (e as campanhas e estatísticas ligadas a elas).

As vitrines novas e as mudanças de nome/lugar não precisam deste script: a API as aplica sozinha ao subir.
Aqui só se APAGA, então ele não roda sozinho: por padrão só mostra o que seria removido; para apagar de verdade, --apply.

    Simulação:   PYTHONPATH=. python scripts/atualizar_vitrines.py
    Apagar:      PYTHONPATH=. python scripts/atualizar_vitrines.py --apply
    Servidor:    cd ~/front-super-fas && sudo docker compose exec -T api python - --apply < ../back-super-fas/scripts/atualizar_vitrines.py

Retiradas (ambiente): evento, drops, feed_2, feed_3, feed_4. Retiradas (fã clubes): mural, feed_2, feed_3.
"""

import sys

from sqlalchemy import delete, func, select

from app import models as m
from app.db import SessionLocal
from app.defaults import RETIRED_CLUB_SLOTS, RETIRED_ENV_SLOTS

apply = "--apply" in sys.argv

with SessionLocal() as db:
    old = [
        s
        for s in db.scalars(select(m.AdSlot))
        if (s.club_id is None and s.key in RETIRED_ENV_SLOTS) or (s.club_id is not None and s.key.split(".")[-1] in RETIRED_CLUB_SLOTS)
    ]
    slot_ids = [s.id for s in old]
    camp_ids = list(db.scalars(select(m.Campaign.id).where(m.Campaign.slot_id.in_(slot_ids)))) if slot_ids else []
    stats = db.scalar(select(func.count()).select_from(m.AdStat).where(m.AdStat.campaign_id.in_(camp_ids))) if camp_ids else 0
    by_key: dict[str, int] = {}
    for s in old:
        k = s.key.split(".")[-1] + (" (fã clube)" if s.club_id else " (ambiente)")
        by_key[k] = by_key.get(k, 0) + 1
    print(f"{len(old)} vitrines, {len(camp_ids)} campanhas e {stats} linhas de estatística {'serão apagadas' if not apply else 'APAGADAS'}.")
    for k, n in sorted(by_key.items()):
        print(f"  {k}: {n}")
    if camp_ids:
        for c in db.scalars(select(m.Campaign).where(m.Campaign.id.in_(camp_ids))):
            print(f"  campanha: {c.brand or (c.sponsor.brand if c.sponsor else '?')} · {c.title} · {c.status}")
    if not apply:
        print("Nada foi apagado. Para apagar de verdade, rode de novo com --apply.")
        raise SystemExit(0)
    if camp_ids:
        db.execute(delete(m.AdStat).where(m.AdStat.campaign_id.in_(camp_ids)))
        db.execute(delete(m.Campaign).where(m.Campaign.id.in_(camp_ids)))
    if slot_ids:
        db.execute(delete(m.AdSlot).where(m.AdSlot.id.in_(slot_ids)))
    db.commit()
    print("Pronto.")
