"""Ranking "Fã Super": o fã compartilha um post oficial no Instagram e pontua quando a legenda leva a hashtag."""

from sqlalchemy import func, select

from fastapi import APIRouter, HTTPException, status

from .. import instagram
from .. import models as m
from ..config import get_settings
from ..schemas import Camel
from ..security import DB, CurrentUser, ManagedArtist, get_club_or_404
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


def _pins(db, artist: m.Artist) -> dict[str | None, str]:
    """{club_id (None = geral): user_id} do fã que a administração fixou em 1º."""
    return {p.club_id: p.user_id for p in db.scalars(select(m.RankingPin).where(m.RankingPin.artist_id == artist.id))}


def _with_leader(rows: list, leader: str | None) -> list:
    """Põe o fã fixado pela administração em 1º (mesmo sem compartilhamentos); os demais seguem a ordem do placar."""
    if not leader:
        return rows
    mine = next((r for r in rows if r[0] == leader), None) or (leader, 0, None)
    return [mine] + [r for r in rows if r[0] != leader]


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
    pins = _pins(db, artist)
    board = _with_leader(_board(db, artist), pins.get(None))
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
        rows = _with_leader([r for r in board if r[0] in member_ids], pins.get(c.id) if pins.get(c.id) in member_ids else None)
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


# ---------- administração: quem lidera o ranking ----------


class LeaderOut(Camel):
    user_id: str
    name: str
    handle: str = ""
    avatar: str | None = None


class LeaderScope(Camel):
    club_slug: str | None = None  # None = ranking geral
    name: str
    leader: LeaderOut | None = None  # None = ninguém fixado: vale a ordem do placar
    top: LeaderOut | None = None  # quem lidera pelo placar de verdade (sem o ajuste da administração)


class LeaderIn(Camel):
    club_slug: str | None = None
    user_id: str | None = None  # None = tira o ajuste e volta ao placar


class FanHit(Camel):
    user_id: str
    name: str
    handle: str = ""
    avatar: str | None = None


def _leader_out(u: m.User | None) -> LeaderOut | None:
    return LeaderOut(user_id=u.id, name=u.name, handle=u.handle or "", avatar=u.avatar_path or None) if u else None


def _club_member_ids(c: m.FanClub) -> set[str]:
    return {mb.user_id for mb in c.members} | {st.user_id for st in c.staff}


@router.get("/artists/{slug}/manage/ranking", response_model=list[LeaderScope])
def manage_ranking(artist: ManagedArtist, db: DB):
    """Quem lidera o ranking geral e o de cada fã clube, e quem lideraria pelo placar."""
    pins, board = _pins(db, artist), _board(db, artist)
    scopes: list[tuple[m.FanClub | None, set[str] | None]] = [(None, None)]
    scopes += [(c, _club_member_ids(c)) for c in sorted(artist.clubs, key=lambda c: (not c.is_master, c.position, c.created_at)) if c.status == "active"]
    ids = set(pins.values())
    tops: list[str | None] = []
    for c, members in scopes:
        rows = [r for r in board if members is None or r[0] in members]
        tops.append(rows[0][0] if rows else None)
    ids |= {t for t in tops if t}
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_(ids)))} if ids else {}
    out = []
    for (c, members), top in zip(scopes, tops):
        pin = pins.get(c.id if c else None)
        out.append(
            LeaderScope(
                club_slug=c.slug if c else None,
                name=c.name if c else "Ranking geral",
                leader=_leader_out(users.get(pin)) if pin and (members is None or pin in members) else None,
                top=_leader_out(users.get(top)) if top else None,
            )
        )
    return out


@router.get("/artists/{slug}/manage/ranking/fans", response_model=list[FanHit])
def search_fans(artist: ManagedArtist, db: DB, q: str = "", club: str | None = None):
    """Busca fãs do ambiente (nome, @ ou e-mail) para escolher quem fica em 1º. Com `club`, só quem é do fã clube."""
    term = q.strip().lower()
    if len(term) < 2:
        return []
    club_ids = [c.id for c in artist.clubs]
    ids = {mb.user_id for mb in db.scalars(select(m.ClubMember).where(m.ClubMember.club_id.in_(club_ids)))} if club_ids else set()
    ids |= {f.user_id for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == artist.id))}
    if club:
        ids &= _club_member_ids(get_club_or_404(db, artist, club))
    if not ids:
        return []
    like = f"%{term}%"
    users = db.scalars(
        select(m.User)
        .where(m.User.id.in_(ids), (func.lower(m.User.name).like(like)) | (func.lower(m.User.handle).like(like)) | (func.lower(m.User.email).like(like)))
        .order_by(m.User.name)
        .limit(15)
    )
    return [FanHit(user_id=u.id, name=u.name, handle=u.handle or "", avatar=u.avatar_path or None) for u in users]


@router.put("/artists/{slug}/manage/ranking/leader", response_model=LeaderScope)
def set_leader(body: LeaderIn, artist: ManagedArtist, db: DB):
    """Fixa um fã em 1º no ranking geral (sem `clubSlug`) ou no de um fã clube; sem `userId` desfaz o ajuste."""
    club = get_club_or_404(db, artist, body.club_slug) if body.club_slug else None
    user = None
    if body.user_id:
        user = db.get(m.User, body.user_id)
        in_env = user and (
            db.scalar(select(m.Fandom.id).where(m.Fandom.artist_id == artist.id, m.Fandom.user_id == user.id))
            or db.scalar(select(m.ClubMember.id).where(m.ClubMember.user_id == user.id, m.ClubMember.club_id.in_([c.id for c in artist.clubs])))
        )
        if not in_env:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã não encontrado neste ambiente.")
        if club and user.id not in _club_member_ids(club):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esse fã não é do fã clube.")
    for p in db.scalars(select(m.RankingPin).where(m.RankingPin.artist_id == artist.id, m.RankingPin.club_id == (club.id if club else None))):
        db.delete(p)
    if user:
        db.add(m.RankingPin(artist_id=artist.id, club_id=club.id if club else None, user_id=user.id))
    db.commit()
    return LeaderScope(club_slug=club.slug if club else None, name=club.name if club else "Ranking geral", leader=_leader_out(user))
