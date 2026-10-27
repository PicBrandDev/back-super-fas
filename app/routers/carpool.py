"""Caronas por show: um fã oferece vagas do carro e o preço de cada uma; outros fãs reservam e pagam.

O valor pago fica RETIDO até a viagem: o passageiro confirma que chegou (ou passam 24 h da saída) e aí é liberado ao
motorista; se a viagem for cancelada a tempo, é devolvido. O pagamento é simulado enquanto não há gateway.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import Field
from sqlalchemy import func, select

from .. import models as m
from ..carpool.models import B_CANCELLED, B_COMPLETED, B_PAID, B_REFUNDED, B_RESERVED, R_CANCELLED, R_OPEN, Ride, RideBooking, RideLedger, utcnow
from ..config import get_settings
from ..schemas import Camel
from ..security import DB, CurrentUser, ManagedArtist
from .fan import FanArtist

router = APIRouter(tags=["Caronas"])

HOLD_MINUTES = 15  # prazo para pagar depois de reservar
AUTO_RELEASE_HOURS = 24  # depois da saída, sem disputa, o valor é liberado ao motorista
REFUND_BEFORE_HOURS = 24  # o passageiro só cancela pagando-se de volta com pelo menos esta antecedência
MAX_OPEN_RIDES = 3  # por motorista e show
LIVE = (B_RESERVED, B_PAID, B_COMPLETED)  # reservas que ocupam vaga


class Who(Camel):
    id: str
    name: str
    handle: str = ""
    avatar: str | None = None


class RideIn(Camel):
    origin_city: str = Field(min_length=2, max_length=80)
    meeting_point: str = Field(default="", max_length=160)
    depart_at: datetime
    seats: int = Field(ge=1, le=8)
    price_cents: int = Field(ge=0, le=100_000)  # até R$ 1.000 por vaga
    car: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=300)


class BookIn(Camel):
    seats: int = Field(default=1, ge=1, le=8)


class BookingOut(Camel):
    id: str
    seats: int
    amount_cents: int
    status: str  # reserved | paid | completed | cancelled | refunded
    expires_at: datetime | None = None
    passenger: Who | None = None  # só para o motorista e a administração


class RideOut(Camel):
    id: str
    event_id: str
    city: str  # cidade do show
    origin_city: str
    meeting_point: str
    depart_at: datetime
    seats_total: int
    seats_left: int
    price_cents: int
    car: str
    notes: str
    status: str
    driver: Who
    mine: bool  # é a viagem do fã logado
    my_booking: BookingOut | None = None
    passengers: list[BookingOut] = []  # só para o dono da viagem


class MyBooking(BookingOut):
    ride: RideOut


class MyCarpool(Camel):
    offered: list[RideOut]
    booked: list[MyBooking]


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _who(u: m.User | None) -> Who:
    return Who(id=u.id, name=u.name, handle=u.handle or "", avatar=u.avatar_path or None) if u else Who(id="", name="Fã removido")


def _event(db, artist: m.Artist, event_id: str) -> m.Event:
    e = db.get(m.Event, event_id)
    if not e or e.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show não encontrado.")
    return e


def _ride(db, artist: m.Artist, ride_id: str) -> Ride:
    r = db.get(Ride, ride_id)
    if not r or r.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Viagem não encontrada.")
    return r


def _expire(db, ride_ids: list[str]) -> None:
    """Reservas sem pagamento que passaram do prazo liberam as vagas; pagas há mais de 24 h da saída são liberadas."""
    now = utcnow()
    if not ride_ids:
        return
    rows = db.execute(select(RideBooking, Ride).join(Ride, Ride.id == RideBooking.ride_id).where(RideBooking.ride_id.in_(ride_ids))).all()
    for b, r in rows:
        if b.status == B_RESERVED and b.expires_at and _aware(b.expires_at) < now:
            b.status = B_CANCELLED
        elif b.status == B_PAID and _aware(r.depart_at) + timedelta(hours=AUTO_RELEASE_HOURS) < now:
            _release(db, b, "automático, 24 h depois da saída")
    db.flush()


def _release(db, b: RideBooking, note: str) -> None:
    fee = b.amount_cents * get_settings().carpool_fee_bps // 10_000
    b.status = B_COMPLETED
    b.completed_at = utcnow()
    db.add(RideLedger(booking_id=b.id, kind="release", amount_cents=b.amount_cents - fee, fee_cents=fee, note=note))


def _refund(db, b: RideBooking, note: str) -> None:
    b.status = B_REFUNDED
    db.add(RideLedger(booking_id=b.id, kind="refund", amount_cents=b.amount_cents, note=note))


def _left(db, r: Ride) -> int:
    used = db.scalar(select(func.coalesce(func.sum(RideBooking.seats), 0)).where(RideBooking.ride_id == r.id, RideBooking.status.in_(LIVE))) or 0
    return max(0, r.seats_total - used)


def _booking_out(b: RideBooking, users: dict[str, m.User], show_passenger: bool) -> BookingOut:
    return BookingOut(
        id=b.id, seats=b.seats, amount_cents=b.amount_cents, status=b.status, expires_at=b.expires_at if b.status == B_RESERVED else None,
        passenger=_who(users.get(b.passenger_id)) if show_passenger else None,
    )


def _ride_out(db, r: Ride, me: m.User, event: m.Event | None = None) -> RideOut:
    bookings = list(db.scalars(select(RideBooking).where(RideBooking.ride_id == r.id).order_by(RideBooking.created_at)))
    ids = {r.driver_id} | {b.passenger_id for b in bookings}
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_(ids)))}
    event = event or db.get(m.Event, r.event_id)
    mine = r.driver_id == me.id
    mb = next((b for b in bookings if b.passenger_id == me.id and b.status in (B_RESERVED, B_PAID, B_COMPLETED)), None)
    return RideOut(
        id=r.id, event_id=r.event_id, city=event.city if event else "", origin_city=r.origin_city, meeting_point=r.meeting_point,
        depart_at=_aware(r.depart_at), seats_total=r.seats_total, seats_left=_left(db, r), price_cents=r.price_cents, car=r.car, notes=r.notes,
        status=r.status, driver=_who(users.get(r.driver_id)), mine=mine,
        my_booking=_booking_out(mb, users, False) if mb else None,
        passengers=[_booking_out(b, users, True) for b in bookings if b.status in (B_PAID, B_COMPLETED, B_RESERVED)] if mine else [],
    )


@router.get("/artists/{slug}/carpool/events/{event_id}/rides", response_model=list[RideOut])
def list_rides(event_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """Viagens abertas para o show, as mais cedo primeiro."""
    e = _event(db, artist, event_id)
    ids = list(db.scalars(select(Ride.id).where(Ride.event_id == e.id)))
    _expire(db, ids)
    rides = db.scalars(select(Ride).where(Ride.event_id == e.id, Ride.status == R_OPEN).order_by(Ride.depart_at)).all()
    out = [_ride_out(db, r, user, e) for r in rides if _aware(r.depart_at) > utcnow() or r.driver_id == user.id]
    db.commit()
    return out


@router.post("/artists/{slug}/carpool/events/{event_id}/rides", response_model=RideOut, status_code=201)
def offer_ride(event_id: str, body: RideIn, artist: FanArtist, user: CurrentUser, db: DB):
    """O fã oferece uma viagem para o show: vagas e preço de cada uma."""
    e = _event(db, artist, event_id)
    if e.date < date.today():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este show já aconteceu.")
    depart = _aware(body.depart_at)
    if depart <= utcnow() or depart.date() > e.date + timedelta(days=1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha uma saída futura, até o dia do show.")
    open_now = db.scalar(select(func.count(Ride.id)).where(Ride.event_id == e.id, Ride.driver_id == user.id, Ride.status == R_OPEN)) or 0
    if open_now >= MAX_OPEN_RIDES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Você já tem {MAX_OPEN_RIDES} viagens abertas para este show.")
    r = Ride(
        artist_id=artist.id, event_id=e.id, driver_id=user.id, origin_city=body.origin_city.strip(), meeting_point=body.meeting_point.strip(),
        depart_at=depart, seats_total=body.seats, price_cents=body.price_cents, car=body.car.strip(), notes=body.notes.strip(),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return _ride_out(db, r, user, e)


@router.post("/artists/{slug}/carpool/rides/{ride_id}/bookings", response_model=BookingOut, status_code=201)
def book_seats(ride_id: str, body: BookIn, artist: FanArtist, user: CurrentUser, db: DB):
    """Reserva vagas (seguradas por 15 minutos até o pagamento)."""
    r = _ride(db, artist, ride_id)
    _expire(db, [r.id])
    if r.status != R_OPEN or _aware(r.depart_at) <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta viagem não está mais aberta.")
    if r.driver_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode reservar vaga na sua própria viagem.")
    if db.scalar(select(RideBooking.id).where(RideBooking.ride_id == r.id, RideBooking.passenger_id == user.id, RideBooking.status.in_(LIVE))):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você já tem vagas nesta viagem.")
    if body.seats > _left(db, r):
        raise HTTPException(status.HTTP_409_CONFLICT, "Não há vagas suficientes.")
    b = RideBooking(ride_id=r.id, passenger_id=user.id, seats=body.seats, amount_cents=body.seats * r.price_cents, expires_at=utcnow() + timedelta(minutes=HOLD_MINUTES))
    db.add(b)
    db.commit()
    db.refresh(b)
    return _booking_out(b, {}, False)


def _booking(db, artist: m.Artist, booking_id: str, user: m.User, driver_ok: bool = False) -> tuple[RideBooking, Ride]:
    b = db.get(RideBooking, booking_id)
    r = db.get(Ride, b.ride_id) if b else None
    if not b or not r or r.artist_id != artist.id or not (b.passenger_id == user.id or (driver_ok and r.driver_id == user.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reserva não encontrada.")
    return b, r


@router.post("/artists/{slug}/carpool/bookings/{booking_id}/pay", response_model=BookingOut)
def pay_booking(booking_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """Paga a reserva. O valor fica retido até a viagem (simulado enquanto não há gateway)."""
    b, r = _booking(db, artist, booking_id, user)
    _expire(db, [r.id])
    if b.status != B_RESERVED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O prazo desta reserva acabou. Reserve de novo." if b.status == B_CANCELLED else "Esta reserva já foi paga.")
    if not get_settings().carpool_allow_fake_payment:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "O pagamento das caronas ainda não está disponível.")
    b.status, b.paid_at, b.expires_at = B_PAID, utcnow(), None
    db.add(RideLedger(booking_id=b.id, kind="hold", amount_cents=b.amount_cents, note="pagamento simulado, retido até a viagem"))
    db.commit()
    return _booking_out(b, {}, False)


@router.post("/artists/{slug}/carpool/bookings/{booking_id}/confirm", response_model=BookingOut)
def confirm_trip(booking_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O passageiro confirma que a viagem aconteceu: o valor retido é liberado ao motorista."""
    b, r = _booking(db, artist, booking_id, user)
    if b.status != B_PAID:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Só dá para confirmar uma viagem paga e ainda não liberada.")
    if _aware(r.depart_at) > utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A viagem ainda não saiu.")
    _release(db, b, "confirmado pelo passageiro")
    db.commit()
    return _booking_out(b, {}, False)


@router.post("/artists/{slug}/carpool/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O passageiro cancela. Pago e com pelo menos 24 h até a saída: devolvemos o valor."""
    b, r = _booking(db, artist, booking_id, user)
    if b.status == B_RESERVED:
        b.status = B_CANCELLED
    elif b.status == B_PAID:
        if _aware(r.depart_at) - utcnow() < timedelta(hours=REFUND_BEFORE_HOURS):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Faltam menos de 24 h para a saída: fale com a administração para cancelar.")
        _refund(db, b, "cancelado pelo passageiro")
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta reserva não pode mais ser cancelada.")
    db.commit()
    return _booking_out(b, {}, False)


@router.post("/artists/{slug}/carpool/rides/{ride_id}/cancel", response_model=RideOut)
def cancel_ride(ride_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O motorista cancela a viagem: todo valor retido é devolvido aos passageiros."""
    r = _ride(db, artist, ride_id)
    if r.driver_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Viagem não encontrada.")
    if r.status != R_OPEN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta viagem já foi cancelada.")
    for b in db.scalars(select(RideBooking).where(RideBooking.ride_id == r.id)):
        if b.status == B_PAID:
            _refund(db, b, "viagem cancelada pelo motorista")
        elif b.status == B_RESERVED:
            b.status = B_CANCELLED
    r.status = R_CANCELLED
    db.commit()
    return _ride_out(db, r, user)


@router.get("/artists/{slug}/carpool/me", response_model=MyCarpool)
def my_carpool(artist: FanArtist, user: CurrentUser, db: DB):
    """As viagens que o fã oferece (com os passageiros) e as vagas que ele reservou."""
    offered = list(db.scalars(select(Ride).where(Ride.artist_id == artist.id, Ride.driver_id == user.id).order_by(Ride.depart_at.desc())))
    mine = list(db.scalars(select(RideBooking).where(RideBooking.passenger_id == user.id).order_by(RideBooking.created_at.desc())))
    rides = {r.id: r for r in db.scalars(select(Ride).where(Ride.id.in_({b.ride_id for b in mine}), Ride.artist_id == artist.id))}
    _expire(db, [r.id for r in offered] + list(rides))
    booked = [
        MyBooking(**_booking_out(b, {}, False).model_dump(), ride=_ride_out(db, rides[b.ride_id], user))
        for b in mine
        if b.ride_id in rides and b.status != B_CANCELLED
    ]
    out = MyCarpool(offered=[_ride_out(db, r, user) for r in offered], booked=booked)
    db.commit()
    return out


# ---------------------------------------------------------------- administração


class CarpoolAdminRow(Camel):
    ride: RideOut
    held_cents: int  # pago e ainda retido
    released_cents: int  # liberado aos motoristas
    refunded_cents: int


class CarpoolAdmin(Camel):
    rides: int
    seats_booked: int
    held_cents: int
    released_cents: int
    refunded_cents: int
    items: list[CarpoolAdminRow]


@router.get("/artists/{slug}/manage/carpool", response_model=CarpoolAdmin)
def carpool_admin(artist: ManagedArtist, user: CurrentUser, db: DB, event: str | None = None):
    """Todas as caronas do ambiente (ou de um show) com o dinheiro retido, liberado e devolvido."""
    q = select(Ride).where(Ride.artist_id == artist.id)
    if event:
        q = q.where(Ride.event_id == event)
    rides = list(db.scalars(q.order_by(Ride.depart_at.desc())))
    _expire(db, [r.id for r in rides])
    items, tot = [], {"held": 0, "released": 0, "refunded": 0}
    seats = 0
    for r in rides:
        bs = list(db.scalars(select(RideBooking).where(RideBooking.ride_id == r.id)))
        held = sum(b.amount_cents for b in bs if b.status == B_PAID)
        rel = sum(b.amount_cents for b in bs if b.status == B_COMPLETED)
        ref = sum(b.amount_cents for b in bs if b.status == B_REFUNDED)
        seats += sum(b.seats for b in bs if b.status in LIVE)
        tot["held"] += held
        tot["released"] += rel
        tot["refunded"] += ref
        items.append(CarpoolAdminRow(ride=_ride_out(db, r, user), held_cents=held, released_cents=rel, refunded_cents=ref))
    db.commit()
    return CarpoolAdmin(rides=len(rides), seats_booked=seats, held_cents=tot["held"], released_cents=tot["released"], refunded_cents=tot["refunded"], items=items)


@router.post("/artists/{slug}/manage/carpool/bookings/{booking_id}/{action}", response_model=BookingOut)
def carpool_support(booking_id: str, action: str, artist: ManagedArtist, db: DB):
    """Suporte: a administração devolve (`refund`) ou libera (`release`) o valor retido de uma reserva paga."""
    b = db.get(RideBooking, booking_id)
    r = db.get(Ride, b.ride_id) if b else None
    if not b or not r or r.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reserva não encontrada.")
    if action not in ("refund", "release"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ação inválida.")
    if b.status != B_PAID:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Só reservas pagas e retidas podem ser devolvidas ou liberadas.")
    (_refund if action == "refund" else _release)(db, b, "pela administração")
    db.commit()
    return _booking_out(b, {}, False)
