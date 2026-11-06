"""Termo de confidencialidade dos ambientes de demonstração: registra quem aceitou (CPF, ambiente, data, IP)."""

from fastapi import APIRouter, HTTPException, status
from pydantic import Field

from .. import models as m
from ..schemas import Camel
from ..security import DB

router = APIRouter(tags=["Termos"])


def cpf_valido(cpf: str) -> bool:
    """11 dígitos, não repetidos, com os dois dígitos verificadores certos."""
    if len(cpf) != 11 or not cpf.isdigit() or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(cpf[i]) * (n + 1 - i) for i in range(n))
        if int(cpf[n]) != (soma * 10 % 11) % 10:
            return False
    return True


class TermsIn(Camel):
    artist_slug: str = Field(min_length=1, max_length=80)
    cpf: str = Field(max_length=20)
    version: str = Field(default="", max_length=20)
    ip: str = Field(default="", max_length=64)
    user_agent: str = Field(default="", max_length=300)


@router.post("/terms/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_terms(body: TermsIn, db: DB):
    cpf = "".join(ch for ch in body.cpf if ch.isdigit())
    if not cpf_valido(cpf):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "CPF inválido. Confira os números.")
    db.add(m.TermsAcceptance(artist_slug=body.artist_slug, cpf=cpf, terms_version=body.version, ip=body.ip, user_agent=body.user_agent))
    db.commit()
