"""Mock de visualizações e cliques por dia das campanhas aprovadas (para ver os gráficos em Admin > Vitrines).

Escreve direto no banco (tabela ad_stats), nos dias em que cada campanha esteve no ar (até 60 dias para trás) e refaz do zero
os números dela, então pode rodar de novo. Os valores são sempre os mesmos para a mesma campanha.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_desempenho_anuncios.py
Local: PYTHONPATH=. python scripts/mock_desempenho_anuncios.py
"""

import random
from datetime import date, timedelta

from sqlalchemy import delete, select

from app import models as m
from app.db import Base, SessionLocal, engine

Base.metadata.create_all(engine)  # garante a tabela ad_stats mesmo antes da API ter subido com o código novo

with SessionLocal() as db:
    today = date.today()
    n = 0
    for c in db.scalars(select(m.Campaign).where(m.Campaign.status == "approved")):
        rnd = random.Random(c.id)
        first = max(c.start or today - timedelta(days=60), today - timedelta(days=60))
        last = min(c.end or today, today)
        db.execute(delete(m.AdStat).where(m.AdStat.campaign_id == c.id))
        base = rnd.randint(150, 1400)
        ctr = rnd.uniform(0.012, 0.06)
        d = first
        while d <= last:
            wave = 1 + 0.35 * ((d.weekday() >= 4) - 0.5)  # sexta a domingo rende mais
            views = max(0, int(base * wave * rnd.uniform(0.7, 1.3)))
            clicks = int(views * ctr * rnd.uniform(0.7, 1.3))
            db.add(m.AdStat(campaign_id=c.id, day=d, views=views, clicks=clicks))
            d += timedelta(days=1)
        n += 1
    db.commit()
    print(f"números de {n} campanhas criados")
