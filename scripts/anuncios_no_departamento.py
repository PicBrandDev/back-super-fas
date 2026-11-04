"""Copia para o Departamento os anúncios que o Vintage Culture já tem, nas mesmas vitrines.

Para cada campanha aprovada do Vintage:
  - vitrine do ambiente (modal de entrada, Início, Mural, roleta, loja...): vai para a mesma vitrine do Departamento;
  - vitrine do fã clube oficial (card do fã clube): vai para o fã clube oficial do Departamento;
  - vitrine de outro fã clube do Vintage (ex.: Brasília, House Sul): fica de fora, porque o Departamento não tem esses clubes.
A campanha vai igual (marca, textos, botão, link, arte, vídeo, período). Não duplica: se a marca já tem a campanha
(mesmo título) na vitrine do Departamento, pula. Os anúncios da Coca-Cola (vídeo antes de girar) e da Red Bull (pós-brinde) já
nascem nos dois ambientes pelos scripts deles; aqui eles aparecem como "já existe".

Servidor: cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/anuncios_no_departamento.py
Local:    PYTHONPATH=. python scripts/anuncios_no_departamento.py
"""

from sqlalchemy import select

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
        else:
            print(f"- {c.brand or c.sponsor.brand} · {slot.name} ({slot.club.name if slot.club else '?'}): fã clube que o Departamento não tem, ficou de fora")
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
    db.commit()
    print(f"\n{criadas} anúncio(s) copiado(s); {puladas} ficaram de fora.")
