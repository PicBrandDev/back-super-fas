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
from .models import ROLE_ARTIST_ADMIN, ROLE_MASTER, ROLE_SPONSOR, Artist, ArtistAdmin, User

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


def admin_slugs(user: User) -> list[str]:
    return sorted(a.artist.slug for a in user.admin_of)


def create_token(user: User) -> str:
    s = get_settings()
    payload = {
        "sub": user.id,
        "role": user.role,
        "name": user.name,
        # O front usa isto para decidir o destino depois do login e liberar /{slug}/admin.
        "artists": admin_slugs(user),
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã clube não encontrado.")
    return artist


def can_manage(db: Session, user: User, artist: Artist) -> bool:
    if user.role == ROLE_MASTER:
        return True
    if user.role != ROLE_ARTIST_ADMIN:
        return False
    return (
        db.scalar(select(ArtistAdmin).where(ArtistAdmin.artist_id == artist.id, ArtistAdmin.user_id == user.id))
        is not None
    )


def managed_artist(slug: str, user: CurrentUser, db: DB) -> Artist:
    """Dependência para rotas /artists/{slug}/... que só o admin do fã clube (ou o master) usa."""
    artist = get_artist_or_404(db, slug)
    if not can_manage(db, user, artist):
        raise forbidden("Só os administradores deste fã clube podem fazer isso.")
    return artist


ManagedArtist = Annotated[Artist, Depends(managed_artist)]
