"""Copia para todos os ambientes ativos os anúncios que o Vintage Culture já tem, nas mesmas vitrines (generaliza o anuncios_no_departamento.py).

Para cada campanha aprovada do Vintage e cada ambiente ativo de destino:
  - vitrine do ambiente (modal de entrada, Início, Mural, notícias, roleta, loja...): vai para a mesma vitrine do destino;
  - vitrine do fã clube oficial: vai para o fã clube oficial do destino;
  - vitrine de outro fã clube do Vintage: vai para o fã clube do destino da mesma cidade; sem cidade igual, vai para o primeiro fã clube
    não oficial do destino (se houver).
A campanha vai igual (marca, textos, botão, link, arte, vídeo, período). No fim, as campanhas do destino sem números ganham visualizações
e cliques por dia (de exemplo). Não duplica: se a marca já tem a campanha (mesmo título) na vitrine, pula.

Para um ambiente só: ALVO=anitta PYTHONPATH=. python scripts/anuncios_nos_ambientes.py
Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/anuncios_nos_ambientes.py
Local:    PYTHONPATH=. python scripts/anuncios_nos_ambientes.py
"""

import os
import random
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app import models as m
from app.db import SessionLocal

ORIGEM = "vintage-culture"
ALVO = os.environ.get("ALVO", "")

with SessionLocal() as db:
    src = db.scalar(select(m.Artist).where(m.Artist.slug == ORIGEM))
    if not src:
        raise SystemExit("Ambiente de origem (vintage-culture) não encontrado.")
    destinos = [a for a in db.scalars(select(m.Artist).where(m.Artist.status == "active").order_by(m.Artist.slug)) if a.id != src.id and (not ALVO or a.slug == ALVO)]
    camps = list(db.scalars(select(m.Campaign).join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id).where(m.AdSlot.artist_id == src.id, m.Campaign.status == "approved")))
    hoje = date.today()

    for dst in destinos:
        dst_master = next((c for c in dst.clubs if c.is_master), None)
        outros = [k for k in dst.clubs if not k.is_master]
        criadas = existentes = puladas = 0
        for c in camps:
            slot = c.slot
            base = slot.key.split(".")[-1]
            if slot.club_id is None:
                target = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == dst.id, m.AdSlot.club_id.is_(None), m.AdSlot.key == slot.key))
            elif slot.club and slot.club.is_master and dst_master:
                target = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == dst.id, m.AdSlot.club_id == dst_master.id, m.AdSlot.key.like(f"%{base}")))
            elif slot.club:
                clube = next((k for k in outros if k.city and k.city == slot.club.city), None) or (outros[0] if outros else None)
                target = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == dst.id, m.AdSlot.club_id == clube.id, m.AdSlot.key.like(f"%{base}"))) if clube else None
            else:
                target = None
            if not target:
                puladas += 1
                continue
            if db.scalar(select(m.Campaign.id).where(m.Campaign.slot_id == target.id, m.Campaign.sponsor_id == c.sponsor_id, m.Campaign.title == c.title)):
                existentes += 1
                continue
            db.add(
                m.Campaign(
                    sponsor_id=c.sponsor_id, slot_id=target.id, brand=c.brand, title=c.title, text=c.text, cta=c.cta, url=c.url, art_path=c.art_path,
                    video_url=c.video_url, target_city=c.target_city, target_radius_km=c.target_radius_km, goal_views=c.goal_views, goal_clicks=c.goal_clicks,
                    start=c.start, end=c.end, status="approved",
                )
            )
            criadas += 1
        db.flush()

        geradas = 0
        for c in list(db.scalars(select(m.Campaign).join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id).where(m.AdSlot.artist_id == dst.id, m.Campaign.status == "approved"))):
            if not c.start or c.start > hoje:
                continue
            total = db.scalar(select(func.coalesce(func.sum(m.AdStat.views), 0)).where(m.AdStat.campaign_id == c.id)) or 0
            if total >= 20:
                continue
            db.execute(delete(m.AdStat).where(m.AdStat.campaign_id == c.id))
            rnd = random.Random(c.id)
            d, fim = c.start, min(c.end or hoje, hoje)
            while d <= fim:
                v = rnd.randint(120, 620)
                db.add(m.AdStat(campaign_id=c.id, day=d, views=v, clicks=max(1, int(v * rnd.uniform(0.012, 0.06)))))
                d += timedelta(days=1)
            geradas += 1
        print(f"{dst.slug}: {criadas} copiada(s), {existentes} já existiam, {puladas} sem vitrine equivalente; {geradas} campanha(s) com números de exemplo")
    db.commit()
print("pronto")
