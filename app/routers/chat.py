"""Chat privado entre fãs do mesmo ambiente (só texto) e o perfil público do fã. Contrato em docs/chat-api.md."""

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import Camel, ClubRef, PostOut, post_out
from ..security import DB, CurrentUser, forbidden
from .fan import FanArtist

router = APIRouter(tags=["Chat"])

MAX_BODY = 1000

# O chat é só de texto: barra imagem embutida, link para foto/vídeo e arquivo enviado ao servidor.
_DATA_URI = re.compile(r"data:[a-z]+/[a-z0-9.+-]+[;,]", re.I)
_MEDIA_EXT = r"jpe?g|png|gif|webp|heic|heif|bmp|svg|avif|tiff?|mp4|mov|webm|m4v|avi|mkv|3gp"
# Link (com http(s)://, www. ou com barra no caminho) que termina numa extensão de mídia, com ou sem ?query/#âncora.
_MEDIA_URL = re.compile(rf"(?:https?://|www\.|\S/)\S*\.(?:{_MEDIA_EXT})(?:[?#]\S*)?(?=$|[\s)\]}}>'\".,;!])", re.I)
_UPLOADS = re.compile(r"/uploads/", re.I)
MEDIA_REFUSED = "O chat é só de texto: não dá para enviar fotos, vídeos ou links de mídia."


class ChatUserOut(Camel):
    id: str
    name: str
    handle: str | None = None
    avatar: str | None = None


class MessageOut(Camel):
    id: int
    conversation_id: int
    sender_id: str
    body: str
    created_at: datetime
    read_at: datetime | None = None
    mine: bool


class ConversationOut(Camel):
    id: int
    other: ChatUserOut
    last_message: MessageOut | None = None
    last_message_at: datetime | None = None
    unread: int = 0


class StartIn(Camel):
    user_id: str | int  # id do usuário é texto; aceita número para não quebrar quem mandar assim


class MessageIn(Camel):
    body: str


class ReadOut(Camel):
    unread: int


class UnreadOut(Camel):
    count: int


class PublicProfileOut(Camel):
    id: str
    name: str
    handle: str | None = None
    avatar: str | None = None
    club: ClubRef | None = None  # fã clube dele neste ambiente
    points: int | None = None  # pontos de sorte neste ambiente
    rank: int | None = None  # posição no ranking Fã Super
    is_me: bool
    posts: list[PostOut] = []


# ---------------------------------------------------------------- utilidades


def user_out(u: m.User) -> ChatUserOut:
    return ChatUserOut(id=u.id, name=u.name, handle=u.handle or None, avatar=u.avatar_path or None)


def message_out(msg: m.Message, me: m.User) -> MessageOut:
    return MessageOut(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        body=msg.body,
        created_at=msg.created_at,
        read_at=msg.read_at,
        mine=msg.sender_id == me.id,
    )


def _unread_q(me: m.User):
    """Mensagens do outro que eu ainda não li."""
    return (m.Message.sender_id != me.id) & m.Message.read_at.is_(None)


def conversation_out(db: Session, c: m.Conversation, me: m.User, unread: int | None = None) -> ConversationOut:
    other = c.user_b if c.user_a_id == me.id else c.user_a
    last = db.scalar(select(m.Message).where(m.Message.conversation_id == c.id).order_by(m.Message.id.desc()).limit(1))
    if unread is None:
        unread = db.scalar(select(func.count(m.Message.id)).where(m.Message.conversation_id == c.id, _unread_q(me))) or 0
    return ConversationOut(
        id=c.id,
        other=user_out(other),
        last_message=message_out(last, me) if last else None,
        last_message_at=c.last_message_at,
        unread=unread,
    )


def _mine(artist: m.Artist, me: m.User):
    return (m.Conversation.artist_id == artist.id) & or_(m.Conversation.user_a_id == me.id, m.Conversation.user_b_id == me.id)


def get_conversation(db: Session, artist: m.Artist, me: m.User, conversation_id: int) -> m.Conversation:
    c = db.get(m.Conversation, conversation_id)
    if not c or c.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada.")
    if me.id not in (c.user_a_id, c.user_b_id):
        raise forbidden("Você não participa desta conversa.")
    return c


def clean_body(raw: str) -> str:
    body = raw.strip()
    if not body:
        raise HTTPException(422, "Escreva uma mensagem.")
    if len(body) > MAX_BODY:
        raise HTTPException(422, f"A mensagem pode ter até {MAX_BODY} caracteres.")
    if _DATA_URI.search(body) or _MEDIA_URL.search(body) or _UPLOADS.search(body):
        raise HTTPException(422, MEDIA_REFUSED)
    return body


# ---------------------------------------------------------------- conversas


@router.get("/artists/{slug}/chat/conversations", response_model=list[ConversationOut])
def list_conversations(artist: FanArtist, user: CurrentUser, db: DB):
    """Minhas conversas neste ambiente, da mais recente para a mais antiga (sem mensagem vai para o fim)."""
    convs = db.scalars(
        select(m.Conversation)
        .where(_mine(artist, user))
        .order_by(m.Conversation.last_message_at.is_(None), m.Conversation.last_message_at.desc(), m.Conversation.id.desc())
    ).all()
    if not convs:
        return []
    counts = dict(
        db.execute(
            select(m.Message.conversation_id, func.count(m.Message.id))
            .where(m.Message.conversation_id.in_([c.id for c in convs]), _unread_q(user))
            .group_by(m.Message.conversation_id)
        ).all()
    )
    return [conversation_out(db, c, user, counts.get(c.id, 0)) for c in convs]


@router.post("/artists/{slug}/chat/conversations", response_model=ConversationOut)
def start_conversation(body: StartIn, artist: FanArtist, user: CurrentUser, db: DB):
    """Abre a conversa com outro fã, ou devolve a que já existe (uma por par em cada ambiente)."""
    other_id = str(body.user_id)
    if other_id == user.id:
        raise HTTPException(422, "Você não pode conversar com você mesmo.")
    other = db.get(m.User, other_id)
    if not other:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã não encontrado.")
    a, b = sorted((user.id, other.id))
    c = db.scalar(
        select(m.Conversation).where(m.Conversation.artist_id == artist.id, m.Conversation.user_a_id == a, m.Conversation.user_b_id == b)
    )
    if not c:
        c = m.Conversation(artist_id=artist.id, user_a_id=a, user_b_id=b)
        db.add(c)
        db.commit()
        db.refresh(c)
    return conversation_out(db, c, user)


@router.get("/artists/{slug}/chat/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation_detail(conversation_id: int, artist: FanArtist, user: CurrentUser, db: DB):
    return conversation_out(db, get_conversation(db, artist, user, conversation_id), user)


# ---------------------------------------------------------------- mensagens


@router.get("/artists/{slug}/chat/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: int,
    artist: FanArtist,
    user: CurrentUser,
    db: DB,
    after_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    """Sem `after_id`: as últimas `limit` mensagens. Com `after_id`: só as novas (polling). Sempre em ordem crescente."""
    c = get_conversation(db, artist, user, conversation_id)
    q = select(m.Message).where(m.Message.conversation_id == c.id)
    if after_id is not None:
        msgs = db.scalars(q.where(m.Message.id > after_id).order_by(m.Message.id).limit(limit)).all()
    else:
        msgs = list(reversed(db.scalars(q.order_by(m.Message.id.desc()).limit(limit)).all()))
    return [message_out(x, user) for x in msgs]


@router.post("/artists/{slug}/chat/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=201)
def send_message(conversation_id: int, body: MessageIn, artist: FanArtist, user: CurrentUser, db: DB):
    c = get_conversation(db, artist, user, conversation_id)
    msg = m.Message(conversation_id=c.id, sender_id=user.id, body=clean_body(body.body), created_at=m.now())
    db.add(msg)
    c.last_message_at = msg.created_at
    db.commit()
    db.refresh(msg)
    return message_out(msg, user)


@router.post("/artists/{slug}/chat/conversations/{conversation_id}/read", response_model=ReadOut)
def mark_read(conversation_id: int, artist: FanArtist, user: CurrentUser, db: DB):
    """Marca como lidas as mensagens do outro nesta conversa."""
    c = get_conversation(db, artist, user, conversation_id)
    db.execute(update(m.Message).where(m.Message.conversation_id == c.id, _unread_q(user)).values(read_at=m.now()))
    db.commit()
    return ReadOut(unread=0)


@router.get("/artists/{slug}/chat/unread", response_model=UnreadOut)
def unread_count(artist: FanArtist, user: CurrentUser, db: DB):
    """Total de não lidas em todas as minhas conversas deste ambiente (badge da navegação)."""
    mine = select(m.Conversation.id).where(_mine(artist, user))
    n = db.scalar(select(func.count(m.Message.id)).where(m.Message.conversation_id.in_(mine), _unread_q(user)))
    return UnreadOut(count=n or 0)


# ---------------------------------------------------------------- perfil público


@router.get("/artists/{slug}/fans/{user_id}", response_model=PublicProfileOut)
def public_profile(user_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """Perfil público de um fã neste ambiente: fã clube, pontos, posição no ranking e os posts mais recentes."""
    from .ranking import _board

    u = db.get(m.User, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã não encontrado.")
    fandom = db.scalar(select(m.Fandom).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == u.id))
    # Fã clube dele neste ambiente: um fã clube da cidade (não master) antes do master.
    clubs = db.scalars(
        select(m.FanClub)
        .join(m.ClubMember, m.ClubMember.club_id == m.FanClub.id)
        .where(m.FanClub.artist_id == artist.id, m.ClubMember.user_id == u.id, m.FanClub.status == "active")
        .order_by(m.FanClub.is_master, m.FanClub.position, m.FanClub.created_at)
    ).all()
    club = clubs[0] if clubs else None
    rank = next((i + 1 for i, (uid, _n, _t) in enumerate(_board(db, artist)) if uid == u.id), None)
    posts = db.scalars(
        select(m.Post).where(m.Post.artist_id == artist.id, m.Post.author_id == u.id).order_by(m.Post.created_at.desc()).limit(10)
    ).all()
    return PublicProfileOut(
        id=u.id,
        name=u.name,
        handle=u.handle or None,
        avatar=u.avatar_path or None,
        club=ClubRef(slug=club.slug, name=club.name, avatar=club.avatar_path or None) if club else None,
        points=fandom.luck_points if fandom else None,
        rank=rank,
        is_me=u.id == user.id,
        posts=[post_out(p, artist) for p in posts],
    )
