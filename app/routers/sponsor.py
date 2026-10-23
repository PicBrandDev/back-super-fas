"""Portal do patrocinador: as campanhas da própria marca."""

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from .. import models as m
from ..config import get_settings
from ..models import new_id
from ..schemas import CampaignOut, SponsorOut, campaign_out, sponsor_out
from ..security import DB, SponsorUser, get_artist_or_404

router = APIRouter(prefix="/sponsor", tags=["Patrocinador"])

ART_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}
MAX_ART_BYTES = 5 * 1024 * 1024


@router.get("/me", response_model=SponsorOut)
def my_sponsor(user: SponsorUser, db: DB):
    sponsor = db.get(m.Sponsor, user.sponsor_id)
    assert sponsor is not None
    return sponsor_out(sponsor)


@router.get("/campaigns", response_model=list[CampaignOut])
def my_campaigns(user: SponsorUser, db: DB):
    q = select(m.Campaign).where(m.Campaign.sponsor_id == user.sponsor_id).order_by(m.Campaign.created_at.desc())
    return [campaign_out(c) for c in db.scalars(q)]


def _parse_date(v: str) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Data inválida: {v}")


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    user: SponsorUser,
    db: DB,
    club: Annotated[str, Form()],
    slot: Annotated[str, Form()],
    title: Annotated[str, Form(min_length=1, max_length=160)],
    link: Annotated[str, Form(max_length=500)] = "",
    brand: Annotated[str, Form(max_length=120)] = "",
    cta: Annotated[str, Form(max_length=60)] = "",
    text: Annotated[str, Form(max_length=2000)] = "",
    start: Annotated[str, Form()] = "",
    end: Annotated[str, Form()] = "",
    city: Annotated[str, Form(max_length=80)] = "",
    radius_km: Annotated[int, Form(ge=0, le=5000)] = 0,
    goal_views: Annotated[int, Form(ge=0, le=100_000_000)] = 0,
    goal_clicks: Annotated[int, Form(ge=0, le=100_000_000)] = 0,
    budget_cents: Annotated[int, Form(ge=0, le=1_000_000_000)] = 0,
    art: Annotated[UploadFile | None, File()] = None,
):
    """Envia uma campanha para aprovação (multipart/form-data, a arte é opcional).

    `club` é o cantor; `slot` é a vitrine (do ambiente, ex. "home", ou de um fã clube, ex. "fa-sp.home").
    """
    artist = get_artist_or_404(db, club)
    if artist.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este fã clube ainda não recebe anúncios.")
    ad_slot = db.scalar(select(m.AdSlot).where(m.AdSlot.artist_id == artist.id, m.AdSlot.key == slot))
    if not ad_slot or not ad_slot.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vitrine indisponível.")
    if ad_slot.club and ad_slot.club.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este fã clube ainda não recebe anúncios.")
    d_start, d_end = _parse_date(start), _parse_date(end)
    if d_start and d_end and d_end < d_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O fim precisa ser depois do início.")

    art_path = ""
    if art and art.filename:
        ext = ART_TYPES.get(art.content_type or "")
        if not ext:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envie a arte em JPG ou PNG.")
        data = await art.read()
        if len(data) > MAX_ART_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A arte pode ter no máximo 5 MB.")
        folder = Path(get_settings().upload_dir)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{new_id()}{ext}"
        (folder / name).write_bytes(data)
        art_path = f"/uploads/{name}"

    sponsor = db.get(m.Sponsor, user.sponsor_id)
    assert sponsor is not None
    if brand.strip() and not sponsor.brand:
        sponsor.brand = brand.strip()
    c = m.Campaign(
        sponsor_id=sponsor.id,
        slot_id=ad_slot.id,
        brand=brand.strip() or sponsor.brand,
        title=title.strip(),
        text=text.strip(),
        cta=cta.strip(),
        url=link.strip(),
        art_path=art_path,
        target_city=city.strip(),
        target_radius_km=radius_km if city.strip() else 0,
        goal_views=goal_views,
        goal_clicks=goal_clicks,
        budget_cents=budget_cents,
        start=d_start,
        end=d_end,
        status="pending",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return campaign_out(c)
