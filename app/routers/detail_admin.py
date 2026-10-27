"""Detalhes de um post (Drop News) e de um hit (Drops Hits) no admin: números, comentários e quem compartilhou (só leitura)."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from .. import models as m
from ..schemas import Camel
from ..security import DB, ManagedArtist

router = APIRouter(tags=["Detalhes no admin"])

LIST_LIMIT = 100


class Who(Camel):
    user_id: str | None = None
    name: str
    handle: str = ""
    avatar: str | None = None


class ShareRow(Who):
    at: datetime
    status: str  # started | claimed | verified
    permalink: str = ""


class CommentRow(Who):
    text: str
    at: datetime


class PostDetail(Camel):
    id: str
    kind: str
    official: bool
    text: str
    image: str | None = None
    url: str = ""
    author: Who | None = None
    club: str | None = None
    created_at: datetime
    likes: int
    comments: int
    reposts: int
    views: int
    shares_total: int
    shares_verified: int
    shares: list[ShareRow]
    comment_list: list[CommentRow]


class TrackDetail(Camel):
    id: str
    title: str
    meta: str
    release_label: str
    duration_sec: int
    likes: int  # votos pela versão completa
    views: int
    shares_total: int
    shares_verified: int
    shares: list[ShareRow]


def _at(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _who(u: m.User | None) -> Who:
    if not u:
        return Who(name="Fã removido")
    return Who(user_id=u.id, name=u.name, handle=u.handle or "", avatar=u.avatar_path or None)


def _shares(db, rows: list[m.InstagramShare]) -> list[ShareRow]:
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_({r.user_id for r in rows})))} if rows else {}
    return [
        ShareRow(**_who(users.get(r.user_id)).model_dump(), at=_at(r.verified_at or r.created_at), status=r.status, permalink=r.permalink)
        for r in rows
    ]


@router.get("/artists/{slug}/manage/posts/{post_id}/detail", response_model=PostDetail)
def post_detail(post_id: str, artist: ManagedArtist, db: DB):
    """Foto, texto, curtidas, comentários (quem comentou e o quê), visualizações e quem compartilhou o post."""
    p = db.get(m.Post, post_id)
    club_ids = {c.id for c in artist.clubs}
    if not p or not (p.artist_id == artist.id or p.club_id in club_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post não encontrado.")
    shares = list(db.scalars(select(m.InstagramShare).where(m.InstagramShare.post_id == p.id).order_by(m.InstagramShare.created_at.desc())))
    replies = sorted(p.replies, key=lambda c: c.created_at, reverse=True)
    return PostDetail(
        id=p.id,
        kind=p.kind,
        official=p.official,
        text=p.text,
        image=p.image_path or None,
        url=p.url,
        author=None if p.official or not p.author else _who(p.author),
        club=p.club.name if p.club else None,
        created_at=_at(p.created_at),
        likes=p.likes,
        comments=max(p.comments, len(replies)),
        reposts=p.reposts,
        views=p.views,
        shares_total=len(shares),
        shares_verified=sum(1 for s in shares if s.status == "verified"),
        shares=_shares(db, shares[:LIST_LIMIT]),
        comment_list=[CommentRow(**_who(c.author).model_dump(), text=c.text, at=_at(c.created_at)) for c in replies[:LIST_LIMIT]],
    )


@router.get("/artists/{slug}/manage/tracks/{track_id}/detail", response_model=TrackDetail)
def track_detail(track_id: str, artist: ManagedArtist, db: DB):
    """Curtidas (votos), visualizações e quem compartilhou o hit."""
    t = db.get(m.Track, track_id)
    if not t or t.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hit não encontrado.")
    shares = list(db.scalars(select(m.InstagramShare).where(m.InstagramShare.track_id == t.id).order_by(m.InstagramShare.created_at.desc())))
    return TrackDetail(
        id=t.id,
        title=t.title,
        meta=t.meta,
        release_label=t.release_label,
        duration_sec=t.duration_sec,
        likes=t.votes,
        views=t.views,
        shares_total=len(shares),
        shares_verified=sum(1 for s in shares if s.status == "verified"),
        shares=_shares(db, shares[:LIST_LIMIT]),
    )
