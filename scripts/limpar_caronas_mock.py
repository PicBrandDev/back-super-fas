"""Apaga as caronas dos mocks (motoristas, passageiros e a fã de teste) para refazê-las do zero com mock_caronas.py.

Só mexe em viagens oferecidas ou reservadas pelas contas de teste (e-mails *.carona@teste.com e a conta de fã de teste).
Caronas de pessoas de verdade ficam como estão.

Rode no servidor:
    cd ~/front-super-fas && sudo docker compose exec -T api python - < ../back-super-fas/scripts/limpar_caronas_mock.py
Fora do container: PYTHONPATH=. python scripts/limpar_caronas_mock.py
"""

from sqlalchemy import delete, or_, select

from app import models as m
from app.carpool.models import Ride, RideBooking, RideLedger
from app.db import SessionLocal

FAN = "juliacristinalopes2607@gmail.com"

with SessionLocal() as db:
    ids = [u.id for u in db.scalars(select(m.User).where(or_(m.User.email.like("%.carona@teste.com"), m.User.email == FAN)))]
    rides = [r.id for r in db.scalars(select(Ride).where(Ride.driver_id.in_(ids)))]
    bookings = [b.id for b in db.scalars(select(RideBooking).where(or_(RideBooking.ride_id.in_(rides), RideBooking.passenger_id.in_(ids))))]
    # reservas de pessoas de verdade em viagens de teste também saem (a viagem some); as de teste em viagens de verdade também
    db.execute(delete(RideLedger).where(RideLedger.booking_id.in_(bookings)))
    db.execute(delete(RideBooking).where(RideBooking.id.in_(bookings)))
    db.execute(delete(Ride).where(Ride.id.in_(rides)))
    db.commit()
    print(f"apagadas {len(rides)} caronas e {len(bookings)} reservas dos mocks")
