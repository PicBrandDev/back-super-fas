"""Identidade do vendedor (CPF e telefone) e elegibilidade para comprar e vender."""

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from .base import ResaleError, conflict, encrypt, pepper_hash, utcnow
from .models import UserIdentity


def clean_cpf(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def valid_cpf(cpf: str) -> bool:
    """CPF com 11 dígitos, não repetido (111.111.111-11) e com os dois dígitos verificadores certos."""
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        if (total * 10 % 11) % 10 != int(cpf[size]):
            return False
    return True


def clean_phone(raw: str) -> str:
    """Telefone brasileiro com DDD (10 ou 11 dígitos), sem o +55."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    return digits


def valid_phone(phone: str) -> bool:
    return len(phone) in (10, 11) and phone[:2] != "00" and (len(phone) == 10 or phone[2] == "9")


def mask_cpf(last2: str) -> str:
    return f"***.***.***-{last2}"


def mask_phone(last4: str) -> str:
    return f"(**) *****-{last4}"


def get(db: Session, user: m.User) -> UserIdentity | None:
    return db.get(UserIdentity, user.id)


def set_identity(db: Session, user: m.User, cpf_raw: str, phone_raw: str) -> UserIdentity:
    """Grava CPF e telefone (cifrados). O CPF não troca depois de definido; um CPF só pode estar em uma conta."""
    cpf, phone = clean_cpf(cpf_raw), clean_phone(phone_raw)
    if not valid_cpf(cpf):
        raise ResaleError("INVALID_CPF", "CPF inválido. Confira os números.")
    if not valid_phone(phone):
        raise ResaleError("INVALID_PHONE", "Telefone inválido. Informe o DDD e o número.")
    digest = pepper_hash(cpf)
    current = get(db, user)
    if current:
        if current.cpf_hash != digest:
            raise conflict("CPF_LOCKED", "O CPF não pode ser trocado depois de informado. Fale com o suporte.")
        current.phone_enc, current.phone_last4 = encrypt(phone), phone[-4:]
        db.commit()
        return current
    other = db.scalar(select(UserIdentity).where(UserIdentity.cpf_hash == digest))
    if other:
        raise conflict("CPF_IN_USE", "Este CPF já está cadastrado em outra conta.")
    ident = UserIdentity(user_id=user.id, cpf_enc=encrypt(cpf), phone_enc=encrypt(phone), cpf_hash=digest, cpf_last2=cpf[-2:], phone_last4=phone[-4:])
    db.add(ident)
    try:
        db.commit()
    except IntegrityError:  # duas contas gravando o mesmo CPF ao mesmo tempo
        db.rollback()
        raise conflict("CPF_IN_USE", "Este CPF já está cadastrado em outra conta.") from None
    return ident


def verify(db: Session, user: m.User, method: str) -> None:
    """Ponto de extensão do MFA por e-mail (fora do escopo agora): quando existir, promove a identidade para 'verified'."""
    raise ResaleError("NOT_IMPLEMENTED", "A verificação por e-mail ainda não está disponível.", 501)


# ---------------------------------------------------------------- elegibilidade


def address_complete(user: m.User) -> bool:
    return all(x.strip() for x in (user.zip_code, user.street, user.number, user.neighborhood, user.city, user.state))


def eligibility(db: Session, artist: m.Artist, user: m.User) -> tuple[bool, bool, list[str]]:
    """(pode comprar, pode vender, o que falta). Fã ou dono de fã clube que entrou neste ambiente e tem cadastro completo;
    vender exige também CPF e telefone. Não exige assinatura de membro."""
    missing: list[str] = []
    if user.role not in (m.ROLE_FAN, m.ROLE_ARTIST_ADMIN):
        return False, False, ["role"]
    from ..routers.fan import get_fandom  # evita import circular

    if not get_fandom(db, artist, user, create=False):  # não cria o Fandom só por consultar
        missing.append("fandom")
    if not address_complete(user):
        missing.append("address")
    can_buy = not missing
    if not get(db, user):
        missing += ["cpf", "phone"]
    return can_buy, not missing, missing
