"""Ranking "Fã Super": o fã compartilha um post oficial no Instagram e pontua quando a legenda leva a hashtag."""

from sqlalchemy import func, select

from fastapi import APIRouter, HTTPException, status

from .. import instagram
from .. import models as m
from ..config import get_settings
from ..schemas import Camel
from ..security import DB, CurrentUser, ManagedArtist
from .fan import FanArtist, get_fandom

router = APIRouter(tags=["Ranking Fã Super"])


class ShareOut(Camel):
    share_id: str
    hashtag: str
    code: str
    caption: str  # legenda pronta para colar no Instagram


class RankRow(Camel):
    position: int
    name: str
    handle: str
    avatar: str | None = None  # foto de perfil do fã
    shares: int
    me: bool = False


class ClaimOut(Camel):
    spin_granted: bool  # False quando o teto de giros do dia já foi atingido (ou o compartilhamento já tinha sido contado)
    already: bool = False


class MyRank(Camel):
    position: int | None  # None = ainda sem compartilhamento confirmado
    shares: int  # confirmados
    pending: int  # compartilhamentos iniciados, ainda sem confirmação


class ClubBoard(Camel):
    slug: str
    name: str
    avatar: str | None = None
    ranked: int  # quantos membros do fã clube já têm compartilhamento confirmado
    me: MyRank | None = None  # None quando o fã não é membro deste fã clube
    top: list[RankRow]


class RankingOut(Camel):
    hashtag: str
    my_code: str
    auto_verify: bool  # a conferência no Instagram está ligada no servidor
    me: MyRank
    top: list[RankRow]  # ranking geral (todos os fãs do ambiente)
    clubs: list[ClubBoard] = []  # ranking de cada fã clube (só os membros dele)


class SyncOut(Camel):
    enabled: bool
    found: int
    verified: int
    error: str | None = None


def _board(db, artist: m.Artist) -> list[tuple[str, int, object]]:
    """[(user_id, compartilhamentos confirmados, primeira confirmação)], do primeiro para o último."""
    q = (
        select(m.InstagramShare.user_id, func.count(m.InstagramShare.id), func.min(m.InstagramShare.verified_at))
        .where(m.InstagramShare.artist_id == artist.id, m.InstagramShare.status == "verified")
        .group_by(m.InstagramShare.user_id)
    )
    rows = list(db.execute(q))
    rows.sort(key=lambda r: (-r[1], r[2] or 0))
    return rows


@router.post("/artists/{slug}/posts/{post_id}/share", response_model=ShareOut, status_code=201)
def start_share(post_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O fã vai compartilhar um post oficial: registra a intenção e devolve a legenda com a hashtag e o código dele."""
    post = db.get(m.Post, post_id)
    if not post or post.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post não encontrado.")
    if not (post.official or post.kind == "drop"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Só os posts oficiais podem ser compartilhados no ranking.")
    f = get_fandom(db, artist, user)
    assert f is not None
    code = instagram.share_code(db, f)
    share = m.InstagramShare(artist_id=artist.id, user_id=user.id, post_id=post.id)
    db.add(share)
    db.commit()
    db.refresh(share)
    return ShareOut(share_id=share.id, hashtag=get_settings().instagram_hashtag, code=code, caption=instagram.caption_for(post.text, code))


@router.post("/artists/{slug}/tracks/{track_id}/share", response_model=ShareOut, status_code=201)
def start_track_share(track_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O fã vai compartilhar um Drop (faixa) no Instagram: também conta para o ranking Fã Super."""
    track = db.get(m.Track, track_id)
    if not track or track.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drop não encontrado.")
    f = get_fandom(db, artist, user)
    assert f is not None
    code = instagram.share_code(db, f)
    share = m.InstagramShare(artist_id=artist.id, user_id=user.id, track_id=track.id)
    db.add(share)
    db.commit()
    db.refresh(share)
    text = f"{track.title}" + (f" · {track.meta}" if track.meta else "")
    return ShareOut(share_id=share.id, hashtag=get_settings().instagram_hashtag, code=code, caption=instagram.caption_for(text, code))


@router.post("/artists/{slug}/shares/{share_id}/claim", response_model=ClaimOut)
def claim_share(share_id: str, artist: FanArtist, user: CurrentUser, db: DB):
    """O fã diz "já postei": rende 1 giro da roleta na hora (o app ainda é de exemplo) e o compartilhamento fica
    aguardando a conferência no Instagram, que é o que pontua no ranking."""
    from .. import spins as spin_lib

    share = db.get(m.InstagramShare, share_id)
    if not share or share.user_id != user.id or share.artist_id != artist.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compartilhamento não encontrado.")
    if share.status != "started":
        return ClaimOut(spin_granted=False, already=True)
    share.status = "claimed"
    f = get_fandom(db, artist, user)
    assert f is not None
    if share.post_id:
        post = db.get(m.Post, share.post_id)
        what = (post.text if post else "post")[:60]
    else:
        track = db.get(m.Track, share.track_id) if share.track_id else None
        what = track.title if track else "drop"
    granted = spin_lib.grant_for_share(db, f, what)
    db.commit()
    return ClaimOut(spin_granted=granted)


@router.get("/artists/{slug}/ranking", response_model=RankingOut)
def ranking(artist: FanArtist, user: CurrentUser, db: DB):
    f = get_fandom(db, artist, user)
    assert f is not None
    code = instagram.share_code(db, f)
    board = _board(db, artist)
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_([r[0] for r in board])))} if board else {}
    top = [
        RankRow(
            position=i + 1,
            name=users[uid].name if uid in users else "Fã",
            handle=(users[uid].handle or "") if uid in users else "",
            avatar=(users[uid].avatar_path or None) if uid in users else None,
            shares=n,
            me=uid == user.id,
        )
        for i, (uid, n, _) in enumerate(board[:30])
    ]
    mine = next(((i + 1, n) for i, (uid, n, _) in enumerate(board) if uid == user.id), None)
    pending = db.scalar(
        select(func.count(m.InstagramShare.id)).where(
            m.InstagramShare.artist_id == artist.id, m.InstagramShare.user_id == user.id, m.InstagramShare.status.in_(("started", "claimed"))
        )
    )
    my_me = MyRank(position=mine[0] if mine else None, shares=mine[1] if mine else 0, pending=pending or 0)

    # Ranking de cada fã clube: o mesmo placar, só com os membros dele.
    clubs = []
    for c in sorted(artist.clubs, key=lambda c: (not c.is_master, c.position, c.created_at)):
        if c.status != "active":
            continue
        # Dono e equipe do fã clube também contam como parte dele (aparecem e pontuam no ranking do fã clube).
        member_ids = {mb.user_id for mb in c.members} | {st.user_id for st in c.staff}
        rows = [r for r in board if r[0] in member_ids]
        names = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_([r[0] for r in rows[:10]])))} if rows else {}
        mine_c = next(((i + 1, n) for i, (uid, n, _) in enumerate(rows) if uid == user.id), None)
        clubs.append(
            ClubBoard(
                slug=c.slug,
                name=c.name,
                avatar=c.avatar_path or None,
                ranked=len(rows),
                me=MyRank(position=mine_c[0] if mine_c else None, shares=mine_c[1] if mine_c else 0, pending=pending or 0) if user.id in member_ids else None,
                top=[
                    RankRow(
                        position=i + 1,
                        name=names[uid].name if uid in names else "Fã",
                        handle=(names[uid].handle or "") if uid in names else "",
                        avatar=(names[uid].avatar_path or None) if uid in names else None,
                        shares=n,
                        me=uid == user.id,
                    )
                    for i, (uid, n, _) in enumerate(rows[:10])
                ],
            )
        )
    db.commit()
    return RankingOut(hashtag=get_settings().instagram_hashtag, my_code=code, auto_verify=instagram.enabled(), me=my_me, top=top, clubs=clubs)


@router.post("/artists/{slug}/manage/instagram/sync", response_model=SyncOut)
def sync_now(artist: ManagedArtist, db: DB):
    """Confere agora os posts da hashtag no Instagram (o servidor também confere sozinho de tempos em tempos)."""
    r = instagram.sync(db, artist)
    return SyncOut(enabled=r.enabled, found=r.found, verified=r.verified, error=r.error)
