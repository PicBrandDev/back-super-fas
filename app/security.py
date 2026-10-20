"""Senhas, tokens de login e as dependências de permissão das rotas."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ROLE_MASTER, ROLE_SPONSOR, STAFF_OWNER, Artist, ClubStaff, FanClub, User

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def temp_password() -> str:
    """Senha provisória legível para contas criadas por convite."""
    return secrets.token_urlsafe(9)


def env_admin_slugs(user: User) -> list[str]:
    """Cantores cujo ambiente a pessoa administra (equipe do fã clube master)."""
    return sorted({st.club.artist.slug for st in user.staff_of if st.club.is_master})


def staff_clubs(user: User) -> list[str]:
    """Fã clubes em que a pessoa é dona ou ajudante, como "cantor/clube"."""
    return sorted(f"{st.club.artist.slug}/{st.club.slug}" for st in user.staff_of)


def create_token(user: User) -> str:
    s = get_settings()
    payload = {
        "sub": user.id,
        "role": user.role,
        "name": user.name,
        # O front usa isto para decidir o destino depois do login e liberar as áreas de admin.
        "artists": env_admin_slugs(user),
        "clubs": staff_clubs(user),
        "exp": datetime.now(timezone.utc) + timedelta(days=s.jwt_days),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def _unauthorized(detail: str = "Faça login para continuar.") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def current_user_optional(request: Request, db: Annotated[Session, Depends(get_db)]) -> User | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise _unauthorized("Sessão expirada. Entre de novo.")
    user = db.get(User, payload.get("sub"))
    if not user:
        raise _unauthorized()
    return user


def current_user(user: Annotated[User | None, Depends(current_user_optional)]) -> User:
    if not user:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(current_user)]
DB = Annotated[Session, Depends(get_db)]


def forbidden(detail: str = "Você não tem permissão para isso.") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)


def require_master(user: CurrentUser) -> User:
    if user.role != ROLE_MASTER:
        raise forbidden()
    return user


def require_sponsor(user: CurrentUser) -> User:
    if user.role != ROLE_SPONSOR or not user.sponsor_id:
        raise forbidden("Só contas de patrocinador podem fazer isso.")
    return user


MasterUser = Annotated[User, Depends(require_master)]
SponsorUser = Annotated[User, Depends(require_sponsor)]


def get_artist_or_404(db: Session, slug: str) -> Artist:
    artist = db.scalar(select(Artist).where(Artist.slug == slug))
    if not artist:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cantor não encontrado.")
    return artist


def staff_role(db: Session, user: User, club: FanClub) -> str | None:
    """"owner", "helper" ou None."""
    st = db.scalar(select(ClubStaff).where(ClubStaff.club_id == club.id, ClubStaff.user_id == user.id))
    return st.role if st else None


def master_club(db: Session, artist: Artist) -> FanClub | None:
    return db.scalar(select(FanClub).where(FanClub.artist_id == artist.id, FanClub.is_master.is_(True)))


def is_env_admin(db: Session, user: User, artist: Artist) -> bool:
    """Admin do ambiente do cantor: admin da plataforma ou equipe do fã clube master."""
    if user.role == ROLE_MASTER:
        return True
    mc = master_club(db, artist)
    return bool(mc and staff_role(db, user, mc))


def is_env_owner(db: Session, user: User, artist: Artist) -> bool:
    """Dono do fã clube master (o "admin master" do cantor) ou admin da plataforma."""
    if user.role == ROLE_MASTER:
        return True
    mc = master_club(db, artist)
    return bool(mc and staff_role(db, user, mc) == STAFF_OWNER)


def can_manage_club(db: Session, user: User, club: FanClub) -> bool:
    return is_env_admin(db, user, club.artist) or staff_role(db, user, club) is not None


# Compatibilidade: "gerenciar o cantor" = administrar o ambiente.
can_manage = is_env_admin


def managed_artist(slug: str, user: CurrentUser, db: DB) -> Artist:
    """Dependência para rotas /artists/{slug}/... do admin do ambiente (equipe do fã clube master)."""
    artist = get_artist_or_404(db, slug)
    if not is_env_admin(db, user, artist):
        raise forbidden("Só a administração do ambiente deste cantor pode fazer isso.")
    return artist


ManagedArtist = Annotated[Artist, Depends(managed_artist)]


def get_club_or_404(db: Session, artist: Artist, club_slug: str) -> FanClub:
    club = db.scalar(select(FanClub).where(FanClub.artist_id == artist.id, FanClub.slug == club_slug))
    if not club:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã clube não encontrado.")
    return club


def managed_club(slug: str, club: str, user: CurrentUser, db: DB) -> FanClub:
    """Dependência para rotas /artists/{slug}/clubs/{club}/... da equipe do fã clube."""
    fc = get_club_or_404(db, get_artist_or_404(db, slug), club)
    if not can_manage_club(db, user, fc):
        raise forbidden("Só a equipe deste fã clube pode fazer isso.")
    return fc


ManagedClub = Annotated[FanClub, Depends(managed_club)]
