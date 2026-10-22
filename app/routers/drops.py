"""Drop News e mural: feed com métricas (admin) e publicação com foto.

O admin do ambiente vê as publicações como cards (curtidas, comentários, visualizações) e
publica um novo Drop News com foto e legenda. Os fãs contam uma visualização por post.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from .. import models as m
from ..schemas import Camel, br_date, time_label
from ..security import DB, CurrentUser, ManagedArtist, ManagedClub
from ..uploads import save_image
from .fan import FanArtist

router = APIRouter(tags=["Drop News"])


class CommentOut(Camel):
    author: str
    text: str
    time_label: str


class FeedItem(Camel):
    id: str
    kind: str
    text: str
    image: str | None = None  # caminho relativo à API (ex.: /uploads/abc.jpg)
    author: str
    handle: str = ""  # @ do autor (vazio para o artista)
    club_name: str | None = None
    time_label: str
    date: str
    likes: int
    comments: int
    reposts: int
    views: int
    recent_comments: list[CommentOut] = []  # os 3 comentários mais recentes


def feed_item(p: m.Post, artist: m.Artist) -> FeedItem:
    author = artist.name if p.official or not p.author else p.author.name
    return FeedItem(
        id=p.id,
        kind=p.kind,
        text=p.text,
        image=p.image_path or None,
        author=author,
        handle="" if p.official or not p.author else (p.author.handle or ""),
        club_name=p.club.name if p.club else None,
        time_label=time_label(p.created_at),
        date=br_date(p.created_at.date()),
        likes=p.likes,
        comments=max(p.comments, len(p.replies)),
        reposts=p.reposts,
        views=p.views,
        recent_comments=[
            CommentOut(author=c.author.name if c.author else "Fã", text=c.text, time_label=time_label(c.created_at))
            for c in p.replies[-3:]
        ],
    )


@router.get("/artists/{slug}/manage/feed", response_model=list[FeedItem])
def feed(artist: ManagedArtist, db: DB, kind: Literal["drop", "galera", "instagram"] = "drop"):
    """Publicações de uma aba, das mais novas para as mais antigas."""
    q = select(m.Post).where(m.Post.artist_id == artist.id, m.Post.kind == kind).order_by(m.Post.created_at.desc()).limit(200)
    return [feed_item(p, artist) for p in db.scalars(q)]


@router.get("/artists/{slug}/clubs/{club}/feed", response_model=list[FeedItem])
def club_feed(club: ManagedClub, db: DB):
    """Todas as publicações de um fã clube, das mais novas para as mais antigas.

    No fã clube master entram também os Drop News oficiais do artista (a equipe do master publica).
    """
    where = m.Post.club_id == club.id
    if club.is_master:
        where = where | (m.Post.club_id.is_(None) & (m.Post.kind == "drop"))
    q = select(m.Post).where(m.Post.artist_id == club.artist_id, where).order_by(m.Post.created_at.desc()).limit(200)
    return [feed_item(p, club.artist) for p in db.scalars(q)]


@router.post("/artists/{slug}/manage/drops", response_model=FeedItem, status_code=201)
async def publish_drop(
    artist: ManagedArtist,
    db: DB,
    text: Annotated[str, Form(min_length=1, max_length=2000)],
    image: Annotated[UploadFile | None, File()] = None,
):
    """Publica um Drop News oficial (multipart/form-data: legenda e foto opcional)."""
    image_path = await save_image(image)
    post = m.Post(
        artist_id=artist.id,
        kind="drop",
        official=True,
        text=text.strip(),
        has_image=bool(image_path),
        image_path=image_path,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return feed_item(post, artist)


@router.post("/artists/{slug}/posts/{post_id}/view")
def count_view(post_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """Soma uma visualização (o front chama uma vez por post e sessão)."""
    post = db.get(m.Post, post_id)
    if not post or post.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post não encontrado.")
    post.views += 1
    db.commit()
    return {"views": post.views}
