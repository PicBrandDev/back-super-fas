"""Fã clubes dentro do ambiente de um cantor.

Cada cantor tem quantos fã clubes quiser: o master (cuja equipe administra o ambiente) e os outros,
cada um com um dono e ajudantes. O fã entra em quantos quiser (grátis).
Por fã clube: membros, mural da galera, PicKap e vitrines de anúncio.
"""

import random
import re
import unicodedata
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import rewards
from ..defaults import CLUB_AD_SLOTS, MASTER_CLUB_SLUG, MAX_CLUB_STAFF
from .. import spins
from ..mailer import send_owner_invite
from ..uploads import save_image
from ..schemas import (
    AdSlotOut,
    CampaignOut,
    ClubCreated,
    ClubCreateIn,
    ClubMemberOut,
    ClubPatch,
    ClubPostIn,
    FanClubOut,
    HomeAdOut,
    InviteOut,
    PostOut,
    PrizeOut,
    SpinIn,
    SpinOut,
    StaffInviteIn,
    StaffOut,
    ad_slot_out,
    br_date,
    campaign_out,
    campaign_status,
    fan_club_out,
    post_out,
    staff_out,
)
from ..security import (
    DB,
    CurrentUser,
    ManagedArtist,
    ManagedClub,
    can_manage_club,
    forbidden,
    get_artist_or_404,
    get_club_or_404,
    hash_password,
    is_env_admin,
    is_env_owner,
    staff_role,
    temp_password,
)

router = APIRouter(tags=["Fã clubes"])


# ---------------------------------------------------------------- utilidades (usadas também pelo admin master e pela migração)


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def add_club_slots(db: Session, club: m.FanClub) -> None:
    for i, (key, name, where, fmt, top, height) in enumerate(CLUB_AD_SLOTS):
        db.add(
            m.AdSlot(
                artist_id=club.artist_id,
                club_id=club.id,
                key=f"{club.slug}.{key}",
                name=name,
                where=where,
                format=fmt,
                diagram_top=top,
                diagram_height=height,
                position=i,
            )
        )


def create_club(
    db: Session,
    artist: m.Artist,
    name: str,
    description: str = "",
    city: str = "",
    is_master: bool = False,
    status_: str = "active",
) -> m.FanClub:
    clubs = db.scalars(select(m.FanClub).where(m.FanClub.artist_id == artist.id)).all()
    if is_master and any(c.is_master for c in clubs):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este cantor já tem um fã clube master.")
    taken = {c.slug for c in clubs}
    base = MASTER_CLUB_SLUG if is_master else (slugify(name) or "fa-clube")
    slug, n = base, 2
    while slug in taken or (not is_master and slug == MASTER_CLUB_SLUG):
        slug, n = f"{base}-{n}", n + 1
    club = m.FanClub(
        artist_id=artist.id,
        slug=slug,
        name=name.strip(),
        description=description.strip(),
        city=city.strip(),
        is_master=is_master,
        status=status_,
        position=0 if is_master else len(clubs) + 1,
    )
    db.add(club)
    db.flush()
    add_club_slots(db, club)
    return club


def invite_staff(db: Session, club: m.FanClub, email: str, name: str = "", role: str = m.STAFF_HELPER, role_label: str = "") -> InviteOut:
    """Cria (ou vincula) a conta de alguém da equipe do fã clube. Devolve a senha provisória quando cria.

    Se o papel for "owner" e o clube já tiver dono, o dono anterior vira ajudante.
    """
    email = email.lower()
    staff = db.scalars(select(m.ClubStaff).where(m.ClubStaff.club_id == club.id)).all()
    user = db.scalar(select(m.User).where(m.User.email == email))
    password = None
    if user:
        if user.role not in (m.ROLE_ARTIST_ADMIN,):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{email} já tem uma conta de outro tipo.")
        existing = next((st for st in staff if st.user_id == user.id), None)
        if existing and not (role == m.STAFF_OWNER and existing.role != m.STAFF_OWNER):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{email} já está na equipe deste fã clube.")
    else:
        existing = None
    if not existing and len(staff) >= MAX_CLUB_STAFF:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A equipe deste fã clube já tem {MAX_CLUB_STAFF} pessoas.")

    if not user:
        password = temp_password()
        user = m.User(
            email=email,
            name=name.strip() or email.split("@")[0],
            password_hash=hash_password(password),
            role=m.ROLE_ARTIST_ADMIN,
            must_change_password=True,
        )
        db.add(user)
        db.flush()

    if role == m.STAFF_OWNER:
        for st in staff:
            if st.role == m.STAFF_OWNER and st.user_id != user.id:
                st.role = m.STAFF_HELPER
                if st.role_label == "Dono do fã clube":
                    st.role_label = "Ajudante"
    label = role_label or ("Dono do fã clube" if role == m.STAFF_OWNER else "Ajudante")
    if existing:
        existing.role = role
        existing.role_label = label
    else:
        db.add(m.ClubStaff(club_id=club.id, user_id=user.id, role=role, role_label=label))
    db.flush()
    return InviteOut(email=email, temp_password=password)


def email_owner(club: m.FanClub, invite: InviteOut, name: str = "") -> None:
    """Avisa por e-mail a pessoa que virou dona do fã clube (depois do commit)."""
    invite.email_sent = send_owner_invite(
        invite.email, name, club.name, club.artist.name, club.artist.slug, invite.temp_password
    )


def join(db: Session, club: m.FanClub, user: m.User) -> None:
    if not db.scalar(select(m.ClubMember).where(m.ClubMember.club_id == club.id, m.ClubMember.user_id == user.id)):
        db.add(m.ClubMember(club_id=club.id, user_id=user.id))


def is_member(db: Session, club: m.FanClub, user: m.User) -> bool:
    return db.scalar(select(m.ClubMember).where(m.ClubMember.club_id == club.id, m.ClubMember.user_id == user.id)) is not None


def visible_club(db: Session, slug: str, club_slug: str, user: m.User) -> m.FanClub:
    """Fã clube visível para quem está logado (os em configuração só para a equipe)."""
    artist = get_artist_or_404(db, slug)
    if artist.status != "active" and not is_env_admin(db, user, artist):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cantor não encontrado.")
    club = get_club_or_404(db, artist, club_slug)
    if club.status != "active" and not can_manage_club(db, user, club):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fã clube não encontrado.")
    return club


def fan_club(slug: str, club: str, user: CurrentUser, db: DB) -> m.FanClub:
    return visible_club(db, slug, club, user)


FanClubDep = Annotated[m.FanClub, Depends(fan_club)]


# ---------------------------------------------------------------- listar, criar, editar


@router.get("/artists/{slug}/clubs", response_model=list[FanClubOut])
def list_clubs(slug: str, user: CurrentUser, db: DB):
    artist = get_artist_or_404(db, slug)
    env = is_env_admin(db, user, artist)
    if artist.status != "active" and not env:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cantor não encontrado.")
    out = []
    for c in sorted(artist.clubs, key=lambda c: (not c.is_master, c.position, c.created_at)):
        if c.status == "active" or env or staff_role(db, user, c):
            out.append(fan_club_out(c, user))
    return out


@router.get("/artists/{slug}/clubs/{club}", response_model=FanClubOut)
def get_club(club: FanClubDep, user: CurrentUser):
    return fan_club_out(club, user)


@router.post("/artists/{slug}/clubs", response_model=ClubCreated, status_code=201)
def create_club_route(body: ClubCreateIn, artist: ManagedArtist, user: CurrentUser, db: DB):
    """Cria um fã clube no ambiente (só o dono do fã clube master ou o admin da plataforma)."""
    if not is_env_owner(db, user, artist):
        raise forbidden("Só o dono do fã clube master cria fã clubes.")
    club = create_club(db, artist, body.name, body.description, body.city)
    invite = None
    if body.owner_email:
        invite = invite_staff(db, club, str(body.owner_email), body.owner_name, m.STAFF_OWNER)
    db.commit()
    db.refresh(club)
    if invite:
        email_owner(club, invite, body.owner_name)
    return ClubCreated(club=fan_club_out(club, user), invite=invite)


@router.patch("/artists/{slug}/clubs/{club}", response_model=FanClubOut)
def update_club(body: ClubPatch, club: ManagedClub, user: CurrentUser, db: DB):
    data = body.model_dump(exclude_unset=True)
    if "status" in data and not is_env_admin(db, user, club.artist):
        raise forbidden("Só a administração do ambiente coloca fã clubes no ar.")
    if club.is_master and data.get("status") == "setup":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O fã clube master fica sempre no ar.")
    for k, v in data.items():
        if v is not None:
            setattr(club, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    db.refresh(club)
    return fan_club_out(club, user)


@router.post("/artists/{slug}/clubs/{club}/avatar", response_model=FanClubOut)
async def set_club_avatar(club: ManagedClub, user: CurrentUser, db: DB, image: Annotated[UploadFile, File()]):
    """Troca a foto de perfil do fã clube (JPG, PNG ou WebP, até 5 MB)."""
    club.avatar_path = await save_image(image)
    db.commit()
    db.refresh(club)
    return fan_club_out(club, user)


@router.delete("/artists/{slug}/clubs/{club}", status_code=204)
def delete_club(club: ManagedClub, user: CurrentUser, db: DB):
    if not is_env_owner(db, user, club.artist):
        raise forbidden("Só o dono do fã clube master apaga fã clubes.")
    if club.is_master:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O fã clube master não pode ser apagado.")
    db.delete(club)
    db.commit()


# ---------------------------------------------------------------- fã: entrar e sair


@router.post("/artists/{slug}/clubs/{club}/join", response_model=FanClubOut)
def join_club(club: FanClubDep, user: CurrentUser, db: DB):
    join(db, club, user)
    db.commit()
    db.refresh(club)
    return fan_club_out(club, user)


@router.post("/artists/{slug}/clubs/{club}/leave", response_model=FanClubOut)
def leave_club(club: FanClubDep, user: CurrentUser, db: DB):
    mb = db.scalar(select(m.ClubMember).where(m.ClubMember.club_id == club.id, m.ClubMember.user_id == user.id))
    if mb:
        db.delete(mb)
        db.commit()
    db.refresh(club)
    return fan_club_out(club, user)


# ---------------------------------------------------------------- mural do fã clube


@router.get("/artists/{slug}/clubs/{club}/posts", response_model=list[PostOut])
def club_posts(club: FanClubDep, db: DB, kind: str | None = None):
    q = select(m.Post).where(m.Post.club_id == club.id)
    if kind:
        q = q.where(m.Post.kind == kind)
    return [post_out(p, club.artist) for p in db.scalars(q.order_by(m.Post.created_at.desc()).limit(100))]


def _reward_post(db: Session, club: m.FanClub, user: m.User) -> bool:
    """Postar rende 1 giro da roleta (até 3 por dia)."""
    from .fan import get_fandom  # evita import circular

    f = get_fandom(db, club.artist, user)
    assert f is not None
    return spins.grant_for_post(db, f, club.name)


@router.post("/artists/{slug}/clubs/{club}/posts", response_model=PostOut, status_code=201)
def create_club_post(body: ClubPostIn, club: FanClubDep, user: CurrentUser, db: DB):
    if not is_member(db, club, user) and not can_manage_club(db, user, club):
        raise forbidden("Entre no fã clube para postar no mural dele.")
    post = m.Post(
        artist_id=club.artist_id, club_id=club.id, kind=body.kind, author_id=user.id, text=body.text.strip(), url=body.url.strip()
    )
    db.add(post)
    rewarded = _reward_post(db, club, user)
    db.commit()
    db.refresh(post)
    out = post_out(post, club.artist)
    out.reward_spin = rewarded
    return out


@router.post("/artists/{slug}/clubs/{club}/posts/media", response_model=PostOut, status_code=201)
async def create_club_post_media(
    club: FanClubDep,
    user: CurrentUser,
    db: DB,
    text: Annotated[str, Form(min_length=1, max_length=2000)],
    image: Annotated[UploadFile | None, File()] = None,
):
    """Post do fã só com texto ou texto com foto (multipart/form-data; JPG, PNG ou WebP, até 5 MB)."""
    if not is_member(db, club, user) and not can_manage_club(db, user, club):
        raise forbidden("Entre no fã clube para postar no mural dele.")
    image_path = await save_image(image)
    post = m.Post(
        artist_id=club.artist_id,
        club_id=club.id,
        kind="galera",
        author_id=user.id,
        text=text.strip(),
        has_image=bool(image_path),
        image_path=image_path,
    )
    db.add(post)
    rewarded = _reward_post(db, club, user)
    db.commit()
    db.refresh(post)
    out = post_out(post, club.artist)
    out.reward_spin = rewarded
    return out


# ---------------------------------------------------------------- PicKap do fã clube


def club_prizes(db: Session, club: m.FanClub) -> list[m.Prize]:
    return list(db.scalars(select(m.Prize).where(m.Prize.club_id == club.id).order_by(m.Prize.position)))


@router.get("/artists/{slug}/clubs/{club}/pickap/prizes", response_model=list[PrizeOut])
def list_club_prizes(club: FanClubDep, db: DB):
    return [PrizeOut(id=p.id, label=p.label, is_retry=p.is_retry or None, kind=p.kind) for p in club_prizes(db, club)]


def spin_wheel(db: Session, club: m.FanClub, user: m.User, credit_id: str | None = None) -> SpinOut:
    """O servidor sorteia o prêmio. Os giros e pontos são do fã no ambiente do cantor."""
    from .fan import get_fandom  # evita import circular

    prizes = club_prizes(db, club)
    if not prizes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A roleta deste fã clube ainda não tem prêmios.")
    f = get_fandom(db, club.artist, user)
    assert f is not None
    credit = spins.take(db, f, credit_id)
    prize = random.choice(prizes)
    spins.use(credit, prize.label)
    if prize.is_retry:
        spins.grant(db, f, spins.RETRY)
    f.luck_points += prize.points
    reward = rewards.create_for(db, club, user, prize)
    spins.sync(db, f)
    db.commit()
    return SpinOut(
        prize=PrizeOut(id=prize.id, label=prize.label, is_retry=prize.is_retry or None, kind=prize.kind),
        reward=rewards.out(db, reward) if reward else None,
        spins_left=f.spins,
        luck_points=f.luck_points,
        credits=spins.out(db, f),
    )


@router.post("/artists/{slug}/clubs/{club}/pickap/spin", response_model=SpinOut)
def spin_club(club: FanClubDep, user: CurrentUser, db: DB, body: SpinIn | None = None):
    if not is_member(db, club, user) and not can_manage_club(db, user, club):
        raise forbidden("Entre no fã clube para girar a roleta dele.")
    return spin_wheel(db, club, user, body.credit_id if body else None)


# ---------------------------------------------------------------- vitrines e campanhas do fã clube


def club_slots(club: m.FanClub, db: Session) -> list[m.AdSlot]:
    return list(db.scalars(select(m.AdSlot).where(m.AdSlot.club_id == club.id).order_by(m.AdSlot.position)))


@router.get("/artists/{slug}/clubs/{club}/ad-slots", response_model=list[AdSlotOut])
def list_club_slots(club: FanClubDep, db: DB):
    return [ad_slot_out(db, s) for s in club_slots(club, db)]


def live_ad(db: Session, slot: m.AdSlot | None) -> HomeAdOut | None:
    if not slot or not slot.active:
        return None
    q = select(m.Campaign).where(m.Campaign.slot_id == slot.id, m.Campaign.status == "approved")
    for c in db.scalars(q.order_by(m.Campaign.created_at)):
        if campaign_status(c) == "live":
            return HomeAdOut(sponsor=c.brand or c.sponsor.brand, title=c.title, text=c.text, cta=c.cta or "Saiba mais", url=c.url or "#")
    return None


@router.get("/artists/{slug}/clubs/{club}/ads/home", response_model=HomeAdOut | None)
def club_home_ad(club: FanClubDep, db: DB):
    slot = db.scalar(select(m.AdSlot).where(m.AdSlot.club_id == club.id, m.AdSlot.key == f"{club.slug}.home"))
    return live_ad(db, slot)


@router.get("/artists/{slug}/clubs/{club}/campaigns", response_model=list[CampaignOut])
def club_campaigns(club: ManagedClub, db: DB):
    slot_ids = [s.id for s in club_slots(club, db)]
    q = select(m.Campaign).where(m.Campaign.slot_id.in_(slot_ids)).order_by(m.Campaign.created_at.desc())
    return [campaign_out(c) for c in db.scalars(q)]


# ---------------------------------------------------------------- equipe do fã clube


@router.get("/artists/{slug}/clubs/{club}/staff", response_model=list[StaffOut])
def list_staff(club: ManagedClub):
    return [staff_out(st) for st in sorted(club.staff, key=lambda st: (st.role != m.STAFF_OWNER, st.created_at))]


def can_set_owner(db: Session, user: m.User, club: m.FanClub) -> bool:
    """Quem escolhe o dono: do master, só o dono do master (ou a plataforma); dos outros, a administração do ambiente."""
    return is_env_owner(db, user, club.artist) if club.is_master else is_env_admin(db, user, club.artist)


@router.post("/artists/{slug}/clubs/{club}/staff", response_model=InviteOut, status_code=201)
def add_staff(body: StaffInviteIn, club: ManagedClub, user: CurrentUser, db: DB):
    """Dono: a administração do ambiente define. Ajudantes: o dono do clube (ou o ambiente) convida."""
    boss = can_set_owner(db, user, club)
    if body.role == m.STAFF_OWNER and not boss:
        raise forbidden("Só a administração do ambiente escolhe o dono do fã clube.")
    if body.role == m.STAFF_HELPER and not (boss or staff_role(db, user, club) == m.STAFF_OWNER):
        raise forbidden("Só o dono do fã clube convida ajudantes.")
    out = invite_staff(db, club, str(body.email), body.name, body.role, body.role_label)
    db.commit()
    if body.role == m.STAFF_OWNER:
        email_owner(club, out, body.name)
    return out


@router.delete("/artists/{slug}/clubs/{club}/staff/{staff_id}", status_code=204)
def remove_staff(staff_id: str, club: ManagedClub, user: CurrentUser, db: DB):
    st = db.get(m.ClubStaff, staff_id)
    if not st or st.club_id != club.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pessoa não encontrada na equipe.")
    boss = can_set_owner(db, user, club)
    if st.role == m.STAFF_OWNER:
        if not boss:
            raise forbidden("Só a administração do ambiente remove o dono do fã clube.")
    elif not (boss or staff_role(db, user, club) == m.STAFF_OWNER or st.user_id == user.id):
        raise forbidden("Só o dono do fã clube remove ajudantes.")
    db.delete(st)
    db.commit()


# ---------------------------------------------------------------- membros do fã clube


@router.get("/artists/{slug}/clubs/{club}/members", response_model=list[ClubMemberOut])
def list_club_members(club: ManagedClub, db: DB):
    subs = {
        f.user_id
        for f in db.scalars(select(m.Fandom).where(m.Fandom.artist_id == club.artist_id, m.Fandom.member_status == "active"))
    }
    q = select(m.ClubMember).where(m.ClubMember.club_id == club.id).order_by(m.ClubMember.created_at.desc())
    return [
        ClubMemberOut(
            id=mb.user_id,
            name=mb.user.name,
            handle=mb.user.handle or mb.user.email,
            city=mb.user.city,
            since=br_date(mb.created_at.date()),
            is_subscriber=mb.user_id in subs,
        )
        for mb in db.scalars(q)
    ]


@router.delete("/artists/{slug}/clubs/{club}/members/{user_id}", status_code=204)
def remove_club_member(user_id: str, club: ManagedClub, db: DB):
    mb = db.scalar(select(m.ClubMember).where(m.ClubMember.club_id == club.id, m.ClubMember.user_id == user_id))
    if not mb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membro não encontrado.")
    db.delete(mb)
    db.commit()


# ---------------------------------------------------------------- conteúdo do fã clube (equipe)


from .club_admin import PrizeIn  # noqa: E402

PrizeAdmin = create_model("ClubPrizeAdmin", __base__=PrizeIn, id=(str, ...))
PrizePatch = create_model(
    "ClubPrizePatch",
    __base__=PrizeIn.__base__,
    **{f: (Optional[info.annotation], None) for f, info in PrizeIn.model_fields.items()},  # type: ignore[valid-type]
)


def _prize_out(p: m.Prize) -> Any:
    return PrizeAdmin(id=p.id, **{f: getattr(p, f) for f in PrizeIn.model_fields})


def _club_prize(db: Session, club: m.FanClub, prize_id: str) -> m.Prize:
    p = db.get(m.Prize, prize_id)
    if not p or p.club_id != club.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prêmio não encontrado.")
    return p


@router.get("/artists/{slug}/clubs/{club}/manage/prizes", response_model=list[PrizeAdmin])
def manage_prizes(club: ManagedClub, db: DB):
    return [_prize_out(p) for p in club_prizes(db, club)]


@router.post("/artists/{slug}/clubs/{club}/manage/prizes", response_model=PrizeAdmin, status_code=201)
def create_prize(body: PrizeIn, club: ManagedClub, db: DB):
    p = m.Prize(artist_id=club.artist_id, club_id=club.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _prize_out(p)


@router.patch("/artists/{slug}/clubs/{club}/manage/prizes/{prize_id}", response_model=PrizeAdmin)
def update_prize(prize_id: str, body: PrizePatch, club: ManagedClub, db: DB):  # type: ignore[valid-type]
    p = _club_prize(db, club, prize_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None or not PrizeIn.model_fields[k].is_required():
            setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _prize_out(p)


@router.delete("/artists/{slug}/clubs/{club}/manage/prizes/{prize_id}", status_code=204)
def delete_prize(prize_id: str, club: ManagedClub, db: DB):
    db.delete(_club_prize(db, club, prize_id))
    db.commit()


@router.get("/artists/{slug}/clubs/{club}/manage/posts", response_model=list[PostOut])
def manage_club_posts(club: ManagedClub, db: DB):
    q = select(m.Post).where(m.Post.club_id == club.id).order_by(m.Post.created_at.desc())
    return [post_out(p, club.artist) for p in db.scalars(q)]


@router.delete("/artists/{slug}/clubs/{club}/manage/posts/{post_id}", status_code=204)
def delete_club_post(post_id: str, club: ManagedClub, db: DB):
    p = db.get(m.Post, post_id)
    if not p or p.club_id != club.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post não encontrado.")
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------- meus painéis


@router.get("/me/staff", response_model=list[dict])
def my_staff(user: CurrentUser, db: DB):
    """Fã clubes em que a pessoa está na equipe (para escolher o painel)."""
    out = []
    for st in user.staff_of:
        c = st.club
        out.append(
            {
                "artist": c.artist.slug,
                "artistName": c.artist.name,
                "club": c.slug,
                "clubName": c.name,
                "isMaster": c.is_master,
                "role": st.role,
                "brandColor": c.artist.brand_color,
            }
        )
    return sorted(out, key=lambda x: (x["artistName"], not x["isMaster"], x["clubName"]))

