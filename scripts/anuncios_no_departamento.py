"""Copia para o Departamento os anúncios que o Vintage Culture já tem, nas mesmas vitrines.

Para cada campanha aprovada do Vintage:
  - vitrine do ambiente (modal de entrada, Início, Mural, roleta, loja...): vai para a mesma vitrine do Departamento;
  - vitrine do fã clube oficial (card do fã clube): vai para o fã clube oficial do Departamento;
  - vitrine de outro fã clube do Vintage: vai para o fã clube do Departamento da mesma cidade (Brasília com Brasília); o que não
    tem cidade igual (ex.: House Sul) vai para o Departamento São Paulo.
A campanha vai igual (marca, textos, botão, link, arte, vídeo, período). No fim, as campanhas do Departamento sem números ganham
visualizações e cliques por dia (de exemplo), para a aba Desempenho e os aluguéis não ficarem zerados. Não duplica: se a marca já tem a campanha
(mesmo título) na vitrine do Departamento, pula. Os anúncios da Coca-Cola (vídeo antes de girar) e da Red Bull (pós-brinde) já
nascem nos dois ambientes pelos scripts deles; aqui eles aparecem como "já existe".

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/anuncios_no_departamento.py
Local:    PYTHONPATH=. python scripts/anuncios_no_departamento.py
"""

import random
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app import models as m
from app.db import SessionLocal

ORIGEM, DESTINO = "vintage-culture", "departamento"

with SessionLocal() as db:
    src = db.scalar(select(m.Artist).where(m.Artist.slug == ORIGEM))
    dst = db.scalar(select(m.Artist).where(m.Artist.slug == DESTINO))
    if not src or not dst:
        raise SystemExit("Vintage ou Departamento não encontrado.")
    dst_master = next((c for c in dst.clubs if c.is_master), None)

    camps = list(
        db.scalars(
            select(m.Campaign).join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id).where(m.AdSlot.artist_id == src.id, m.Campaign.status == "approved")
        )
    )
    criadas = puladas = 0
    for c in camps:
        slot = c.slot
        base = slot.key.split(".")[-1]
        if slot.club_id is None:
            target = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == dst.id, m.AdSlot.club_id.is_(None), m.AdSlot.key == slot.key))
            onde = "ambiente"
        elif slot.club and slot.club.is_master and dst_master:
            target = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == dst.id, m.AdSlot.club_id == dst_master.id, m.AdSlot.key.like(f"%{base}")))
            onde = "fã clube oficial"
        elif slot.club:
            clube = next((k for k in dst.clubs if not k.is_master and k.city and k.city == slot.club.city), None) or next(
                (k for k in dst.clubs if k.slug == "departamento-sao-paulo"), None
            )
            if not clube:
                print(f"- {c.brand or c.sponsor.brand} · {slot.name} ({slot.club.name}): sem fã clube equivalente no Departamento, ficou de fora")
                puladas += 1
                continue
            target = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == dst.id, m.AdSlot.club_id == clube.id, m.AdSlot.key.like(f"%{base}")))
            onde = clube.name
        else:
            puladas += 1
            continue
        if not target:
            print(f"- {c.brand or c.sponsor.brand} · {slot.name}: a vitrine não existe no Departamento (suba a API nova), ficou de fora")
            puladas += 1
            continue
        if db.scalar(select(m.Campaign.id).where(m.Campaign.slot_id == target.id, m.Campaign.sponsor_id == c.sponsor_id, m.Campaign.title == c.title)):
            print(f"= {c.brand or c.sponsor.brand} · {slot.name}: já existe no Departamento")
            continue
        db.add(
            m.Campaign(
                sponsor_id=c.sponsor_id,
                slot_id=target.id,
                brand=c.brand,
                title=c.title,
                text=c.text,
                cta=c.cta,
                url=c.url,
                art_path=c.art_path,
                video_url=c.video_url,
                target_city=c.target_city,
                target_radius_km=c.target_radius_km,
                goal_views=c.goal_views,
                goal_clicks=c.goal_clicks,
                start=c.start,
                end=c.end,
                status="approved",
            )
        )
        criadas += 1
        print(f"+ {c.brand or c.sponsor.brand} · {slot.name} ({onde}): copiada para o Departamento ({c.start:%d/%m} a {c.end:%d/%m})" if c.start and c.end else f"+ {c.brand or c.sponsor.brand} · {slot.name} ({onde}): copiada para o Departamento")
    db.flush()

    # Números de exemplo (visualizações e cliques por dia) nas campanhas do Departamento que ainda não têm.
    hoje = date.today()
    geradas = 0
    todas = db.scalars(select(m.Campaign).join(m.AdSlot, m.Campaign.slot_id == m.AdSlot.id).where(m.AdSlot.artist_id == dst.id, m.Campaign.status == "approved"))
    for c in list(todas):
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
    db.commit()
    print(f"\n{criadas} anúncio(s) copiado(s); {puladas} ficaram de fora; {geradas} campanha(s) com números de exemplo.")
