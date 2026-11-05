"""Quais campanhas aprovadas o app do fã realmente mostra? (só lê)"""
from collections import defaultdict

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.routers.fan import IN_APP_SLOTS, PICKUP_LAYER_SLOTS
from app.schemas import campaign_status

LIDAS = set(IN_APP_SLOTS.values()) | set(PICKUP_LAYER_SLOTS) | {"home", "feed_clubes"}  # chaves do ambiente que o app lê

with SessionLocal() as db:
    por_vitrine = defaultdict(list)
    for c in db.scalars(select(m.Campaign).where(m.Campaign.status == "approved").order_by(m.Campaign.created_at)):
        por_vitrine[c.slot_id].append(c)
    total = aparecem = fora_do_ar = vitrine_nao_lida = escondidas = 0
    linhas = []
    for slot_id, camps in por_vitrine.items():
        slot = db.get(m.AdSlot, slot_id)
        env = slot.club_id is None
        chave = slot.key
        lida = (env and chave in LIDAS) or (not env and chave.endswith(".home"))
        no_ar = [c for c in camps if campaign_status(c) == "live"]
        total += len(camps)
        if not lida:
            vitrine_nao_lida += len(camps)
            linhas.append(f"  NAO LIDA  {slot.artist.slug}/{chave}: {len(camps)} ({', '.join(c.brand for c in camps)})")
            continue
        fora_do_ar += len(camps) - len(no_ar)
        if no_ar:
            aparecem += 1
            escondidas += len(no_ar) - 1
            if len(no_ar) > 1:
                linhas.append(f"  SO 1 APARECE  {slot.artist.slug}/{chave}: aparece {no_ar[0].brand}; escondidas: {', '.join(c.brand for c in no_ar[1:])}")
    print(f"campanhas aprovadas: {total}")
    print(f"  em vitrine que o app NAO le: {vitrine_nao_lida}")
    print(f"  fora do periodo (agendadas/encerradas) em vitrine lida: {fora_do_ar}")
    print(f"  no ar mas escondidas por outra mais antiga na mesma vitrine: {escondidas}")
    print(f"  vitrines que mostram anuncio ao fa: {aparecem}")
    print("\n".join(linhas))
