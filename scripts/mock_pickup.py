"""Dados de teste do PicKup: estoque dos brindes e muitos giros e ganhadores em cada roleta (para a aba PicKup do admin).

O que faz, direto no banco, em todas as roletas (uma por fã clube) do ambiente:
  1. define o estoque: cupons de desconto = 1.000, camiseta e boné (retirar na lojinha) = 500; ingressos e as
     fatias "não foi dessa vez" / "gire de novo" ficam sem limite (não mexe no que já tem estoque diferente: use
     ESTOQUE=0 para só criar os giros, sem mudar o estoque);
  2. cria giros usados nos últimos 30 dias, com a fã certa em cada fatia: brindes com código (alguns já retirados,
     alguns cupons já usados) e giros que não deram brinde. A roleta do fã clube oficial (master) recebe bem mais giros.

Pode rodar de novo: apaga os giros e brindes que ele mesmo criou antes (código começando com MK, motivo "Mock PicKup")
e cria de novo. Não mexe nos giros e brindes de verdade.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/mock_pickup.py
"""

import os
import random
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from app import models as m
from app.db import SessionLocal

SLUG = os.environ.get("ARTIST", "vintage-culture")
SET_STOCK = os.environ.get("ESTOQUE", "1") != "0"
REASON = "Mock PicKup"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
NO_REWARD = ("none", "retry")

# Quantos ganhadores cada tipo de fatia tem na roleta do master (nos outros fã clubes, 15% disso).
BASE_WINS = {"coupon": 190, "pickup": 95, "ticket": 40, "none": 120, "retry": 60, "": 30}
STOCK = {"coupon": 1000, "pickup": 500}


def kind_of(p: m.Prize) -> str:
    return "retry" if p.is_retry else (p.kind or "")


def code(taken: set[str], prefix: str = "MK", size: int = 5) -> str:
    while True:
        c = prefix + "".join(secrets.choice(ALPHABET) for _ in range(size - len(prefix)))
        if c not in taken:
            taken.add(c)
            return c


def main() -> None:
    rnd = random.Random(2026)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == SLUG))
        if not artist:
            raise SystemExit(f"ambiente {SLUG} não existe")

        # Limpa o que este script criou numa rodada anterior.
        old = db.scalars(select(m.Reward).where(m.Reward.artist_id == artist.id, m.Reward.code.like("MK%")))
        for r in old:
            if r.coupon_code:
                db.execute(delete(m.Coupon).where(m.Coupon.artist_id == artist.id, m.Coupon.code == r.coupon_code))
            db.delete(r)
        db.execute(delete(m.SpinCredit).where(m.SpinCredit.artist_id == artist.id, m.SpinCredit.reason == REASON))
        db.flush()

        fans = [f.user_id for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id))]
        taken_codes = set(db.scalars(select(m.Reward.code).where(m.Reward.artist_id == artist.id)))
        taken_coupons = set(db.scalars(select(m.Coupon.code).where(m.Coupon.artist_id == artist.id)))
        total_spins = total_rewards = 0

        for club in sorted(artist.clubs, key=lambda c: (not c.is_master, c.position)):
            prizes = list(db.scalars(select(m.Prize).where(m.Prize.club_id == club.id).order_by(m.Prize.position)))
            if not prizes:
                continue
            if SET_STOCK:
                for p in prizes:
                    if kind_of(p) in STOCK:
                        p.stock = STOCK[kind_of(p)]
            pool = fans if club.is_master else [mb.user_id for mb in club.members] or fans
            scale = 1.0 if club.is_master else 0.15
            by_kind: dict[str, list[m.Prize]] = {}
            for p in prizes:
                by_kind.setdefault(kind_of(p), []).append(p)
            for kind, group in by_kind.items():
                per_prize = max(2, round(BASE_WINS.get(kind, 30) * scale / len(group) * (1 if kind != "coupon" else 1)))
                for p in group:
                    cap = per_prize if p.stock is None else min(per_prize, max(0, p.stock - 1))
                    for _ in range(cap):
                        user = rnd.choice(pool)
                        at = now - timedelta(days=rnd.random() * 30, hours=rnd.random() * 6)
                        db.add(
                            m.SpinCredit(
                                artist_id=artist.id, user_id=user, reason=REASON, used_at=at, prize_label=p.label,
                                club_id=club.id, prize_id=p.id, created_at=at - timedelta(minutes=rnd.randint(1, 90)),
                            )
                        )
                        total_spins += 1
                        if kind in NO_REWARD:
                            continue
                        coupon = ""
                        expires = at.date() + timedelta(days=90)
                        if kind == "coupon":
                            coupon = code(taken_coupons, f"ROLETA{p.percent or 10}-MK", len(f"ROLETA{p.percent or 10}-MK") + 2)
                            db.add(
                                m.Coupon(
                                    artist_id=artist.id, user_id=user, code=coupon, kind="percent", value=p.percent or 10, max_uses=1,
                                    used=1 if rnd.random() < 0.35 else 0, expires_on=expires, source="Prêmio da roleta do PicKup",
                                )
                            )
                        old_enough = (now - at) > timedelta(days=3)
                        db.add(
                            m.Reward(
                                artist_id=artist.id, club_id=club.id, user_id=user, label=p.label, kind=p.kind or "", prize_id=p.id,
                                code=code(taken_codes), instructions=p.instructions or "", coupon_code=coupon, expires_on=expires,
                                redeemed_at=at + timedelta(days=rnd.randint(1, 3)) if (kind != "coupon" and old_enough and rnd.random() < 0.55) else None,
                                created_at=at,
                            )
                        )
                        total_rewards += 1
            print(f"  {club.name}: {len(prizes)} fatias")
        db.commit()
        print(f"pronto: {total_spins} giros e {total_rewards} brindes criados. Estoque: cupons 1.000, camiseta e boné 500." if SET_STOCK else f"pronto: {total_spins} giros e {total_rewards} brindes criados.")
        _ = date


main()
