"""Lista, só para leitura, os patrocinadores e as campanhas de cada ambiente: marca, vitrine, onde, período, situação, views e cliques.
Não grava nada. Serve para comparar o que o sistema tem com o que aparece em /admin/midia e em /<artista>/admin/vitrines.

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/listar_vitrines.py
Local:    PYTHONPATH=. python scripts/listar_vitrines.py
"""

from sqlalchemy import func, select

from app import models as m
from app.db import SessionLocal

with SessionLocal() as db:
    print("PATROCINADORES")
    for sp in db.scalars(select(m.Sponsor).order_by(m.Sponsor.brand)):
        n = db.scalar(select(func.count()).select_from(m.Campaign).where(m.Campaign.sponsor_id == sp.id))
        print(f"  {sp.brand:<12} {sp.email:<34} status={sp.status:<8} campanhas={n} login={'sim' if sp.users else 'não'}")

    for art in db.scalars(select(m.Artist).order_by(m.Artist.name)):
        camps = list(
            db.scalars(
                select(m.Campaign).join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id).where(m.AdSlot.artist_id == art.id).order_by(m.Campaign.status, m.Campaign.start)
            )
        )
        if not camps:
            continue
        print(f"\n{art.name.upper()} ({art.slug}): {len(camps)} campanha(s)")
        for c in camps:
            v, k = db.execute(select(func.coalesce(func.sum(m.AdStat.views), 0), func.coalesce(func.sum(m.AdStat.clicks), 0)).where(m.AdStat.campaign_id == c.id)).one()
            onde = c.slot.club.name if c.slot.club else "ambiente"
            periodo = f"{c.start:%d/%m} a {c.end:%d/%m}" if c.start and c.end else "sem datas"
            print(f"  {c.brand or c.sponsor.brand:<10} | {c.slot.name:<42} | {onde:<32} | {periodo:<13} | {c.status:<8} | {int(v):>6} views {int(k):>4} cliques")
