"""Photo Finder: fotos oficiais de cada show (admin) e busca do fã por selfie (AWS Rekognition)."""

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from .. import models as m
from .. import rekognition
from ..config import get_settings
from ..schemas import Camel
from ..security import DB, CurrentUser, ManagedArtist, is_env_admin
from ..uploads import MAX_IMAGE_BYTES, save_image
from .fan import FanArtist, _event

router = APIRouter(tags=["Photo Finder"])

MAX_BATCH = 30


class PhotoOut(Camel):
    id: str
    src: str
    indexed: bool
    faces: int


class FinderStatus(Camel):
    enabled: bool  # reconhecimento ligado no servidor
    photos: int  # fotos do show
    eligible: bool  # este fã pode buscar agora
    reason: str | None = None  # por que não pode


class FinderMatch(Camel):
    id: str
    src: str


class FinderResult(Camel):
    matches: list[FinderMatch]
    searched: int  # quantas fotos do show existem


def photo_out(p: m.EventPhoto) -> PhotoOut:
    return PhotoOut(id=p.id, src=p.path, indexed=p.indexed, faces=len(p.face_ids or []))


def _file_bytes(path: str) -> bytes:
    return (Path(get_settings().upload_dir) / Path(path).name).read_bytes()


def _index(p: m.EventPhoto) -> None:
    if not rekognition.enabled():
        return
    p.face_ids = rekognition.index_photo(p.event_id, p.id, _file_bytes(p.path))
    p.indexed = True


# ---------------------------------------------------------------- admin


def _admin_event(db, artist: m.Artist, event_id: str) -> m.Event:
    e = db.get(m.Event, event_id)
    if not e or e.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evento não encontrado.")
    return e


@router.get("/artists/{slug}/manage/events/{event_id}/photos", response_model=list[PhotoOut])
def list_photos(event_id: str, artist: ManagedArtist, db: DB):
    e = _admin_event(db, artist, event_id)
    q = select(m.EventPhoto).where(m.EventPhoto.event_id == e.id).order_by(m.EventPhoto.created_at)
    return [photo_out(p) for p in db.scalars(q)]


@router.post("/artists/{slug}/manage/events/{event_id}/photos", response_model=list[PhotoOut], status_code=201)
async def upload_photos(event_id: str, artist: ManagedArtist, db: DB, photos: Annotated[list[UploadFile], File()]):
    """Envia as fotos oficiais do show (JPG, PNG ou WebP, até 5 MB cada). Com o Rekognition ligado, indexa os rostos."""
    e = _admin_event(db, artist, event_id)
    if not photos or len(photos) > MAX_BATCH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Envie de 1 a {MAX_BATCH} fotos por vez.")
    out = []
    for f in photos:
        path = await save_image(f)
        if not path:
            continue
        p = m.EventPhoto(artist_id=artist.id, event_id=e.id, path=path)
        db.add(p)
        db.flush()
        _index(p)
        out.append(photo_out(p))
    db.commit()
    return out


@router.post("/artists/{slug}/manage/events/{event_id}/photos/index", response_model=list[PhotoOut])
def index_pending(event_id: str, artist: ManagedArtist, db: DB):
    """Indexa as fotos que ainda não foram indexadas (por exemplo, depois de ligar o Rekognition)."""
    if not rekognition.enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "O reconhecimento facial ainda não foi ligado neste servidor.")
    e = _admin_event(db, artist, event_id)
    q = select(m.EventPhoto).where(m.EventPhoto.event_id == e.id, m.EventPhoto.indexed.is_(False))
    done = []
    for p in db.scalars(q):
        _index(p)
        done.append(photo_out(p))
    db.commit()
    return done


@router.delete("/artists/{slug}/manage/events/{event_id}/photos/{photo_id}", status_code=204)
def delete_photo(event_id: str, photo_id: str, artist: ManagedArtist, db: DB):
    e = _admin_event(db, artist, event_id)
    p = db.get(m.EventPhoto, photo_id)
    if not p or p.event_id != e.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foto não encontrada.")
    rekognition.delete_faces(e.id, list(p.face_ids or []))
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------- fã


def _eligibility(db, artist: m.Artist, user: m.User, e: m.Event) -> str | None:
    """None quando o fã pode buscar; senão, o motivo (em português)."""
    from ..demo import ensure_photo_tickets

    ensure_photo_tickets(db, artist, user)
    if is_env_admin(db, user, artist):
        return None
    if e.date >= date.today():
        return "O Photo Finder abre depois do show."
    has = db.scalar(
        select(m.TicketPurchase).where(
            m.TicketPurchase.user_id == user.id, m.TicketPurchase.event_id == e.id
        )
    )
    if not has:
        return "Você precisa de um ingresso deste show para usar o Photo Finder."
    return None


@router.get("/artists/{slug}/events/{event_id}/photo-finder", response_model=FinderStatus)
def finder_status(event_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    e = _event(db, artist, event_id)
    n = len(db.scalars(select(m.EventPhoto.id).where(m.EventPhoto.event_id == e.id)).all())
    reason = _eligibility(db, artist, user, e)
    if reason is None and not rekognition.enabled():
        reason = "O reconhecimento facial ainda não foi ligado neste servidor."
    if reason is None and n == 0 and not rekognition.shared_enabled():
        reason = "As fotos deste show ainda não foram publicadas."
    return FinderStatus(enabled=rekognition.enabled(), photos=n, eligible=reason is None, reason=reason)


@router.post("/artists/{slug}/events/{event_id}/photo-finder/search", response_model=FinderResult)
async def finder_search(
    event_id: str,
    artist: FanArtist,
    user: CurrentUser,
    db: DB,
    selfie: Annotated[UploadFile, File()],
    consent: Annotated[bool, Form()] = False,
):
    """Procura o rosto da selfie nas fotos do show. A selfie não é guardada."""
    e = _event(db, artist, event_id)
    reason = _eligibility(db, artist, user, e)
    if reason:
        raise HTTPException(status.HTTP_403_FORBIDDEN, reason)
    if not consent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Autorize o uso da sua selfie para procurar suas fotos.")
    if selfie.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envie a selfie em JPG ou PNG.")
    data = await selfie.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A selfie pode ter no máximo 5 MB.")
    if rekognition.shared_enabled():
        # Coleção e bucket configurados: devolve links temporários das fotos do S3 em que a pessoa aparece.
        found = rekognition.presigned_photos(rekognition.search_shared(data))
        return FinderResult(matches=[FinderMatch(id=i, src=url) for i, url in found], searched=0)
    photos = {p.id: p for p in db.scalars(select(m.EventPhoto).where(m.EventPhoto.event_id == e.id))}
    ids = rekognition.search_selfie(e.id, data)
    return FinderResult(matches=[FinderMatch(id=i, src=photos[i].path) for i in ids if i in photos], searched=len(photos))
