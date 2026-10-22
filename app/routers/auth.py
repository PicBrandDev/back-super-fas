from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from .. import models as m
from ..schemas import ChangePasswordIn, LoginIn, RegisterIn, SessionUser, TokenOut, session_user
from ..security import DB, CurrentUser, create_token, hash_password, master_club, verify_password

router = APIRouter(prefix="/auth", tags=["Login"])


def _token_out(user: m.User) -> TokenOut:
    return TokenOut(token=create_token(user), user=session_user(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB):
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha incorretos.")
    if user.role == m.ROLE_SPONSOR and user.sponsor and user.sponsor.status == "invited":
        user.sponsor.status = "active"
        db.commit()
    return _token_out(user)


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: DB):
    """Cadastro aberto só para fãs. Admins e patrocinadores entram por convite."""
    email = body.email.lower()
    if db.scalar(select(m.User).where(m.User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma conta com esse e-mail.")
    handle = body.handle.strip()
    if handle and not handle.startswith("@"):
        handle = "@" + handle
    user = m.User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name.strip(),
        handle=handle,
        city=body.city.strip(),
        zip_code=body.zip_code.strip(),
        street=body.street.strip(),
        number=body.number.strip(),
        complement=body.complement.strip(),
        neighborhood=body.neighborhood.strip(),
        state=body.state.strip().upper(),
        role=m.ROLE_FAN,
    )
    db.add(user)
    if body.artist:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == body.artist))
        if artist:
            db.add(m.Fandom(artist=artist, user=user))
            # Já entra no fã clube master do cantor escolhido.
            mc = master_club(db, artist)
            if mc:
                db.add(m.ClubMember(club_id=mc.id, user=user))
    db.commit()
    db.refresh(user)
    return _token_out(user)


@router.get("/me", response_model=SessionUser)
def me(user: CurrentUser):
    return session_user(user)


@router.post("/change-password", response_model=TokenOut)
def change_password(body: ChangePasswordIn, user: CurrentUser, db: DB):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A senha atual não confere.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    return _token_out(user)
