"""Base da revenda de ingressos: prazos, relógio, dinheiro, erros e cifra de dados sensíveis."""

import base64
import hashlib
import hmac
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from ..config import get_settings

# ---------------------------------------------------------------- prazos e limites

RESERVE_MINUTES = 15  # o comprador tem 15 min para pagar a reserva
TRANSFER_HOURS = 24  # o vendedor transfere em até 24h depois do pagamento...
TRANSFER_MIN_BEFORE_SHOW_H = 2  # ...ou até 2h antes do show, o que vier antes
CONFIRM_HOURS = 48  # sem confirmação nem disputa, o valor é liberado ao vendedor
BLOCK_BUY_BEFORE_SHOW_H = 4  # menos que isso para o show: não vende mais (o vendedor precisa de pelo menos 2h)
MAX_ACTIVE_RESERVATIONS = 3  # reservas em aberto por comprador
MAX_LISTINGS_PER_HOUR = 5  # anúncios criados por vendedor por hora
MAX_ATTEMPTS = 3  # envios da prova por anúncio
MAX_FEE_BPS = 3000  # 30%
PROOF_MAX_BYTES = 8 * 1024 * 1024

# Anúncio
L_PENDING, L_LIVE, L_REJECTED, L_CANCELLED, L_CLOSED = "pending_review", "live", "rejected", "cancelled", "closed"
# Pedido
O_RESERVED, O_AWAITING, O_TRANSFERRED, O_COMPLETED = "reserved", "awaiting_transfer", "transferred", "completed"
O_DISPUTED, O_REFUNDED, O_EXPIRED, O_CANCELLED = "disputed", "refunded", "expired", "cancelled"
O_ACTIVE = (O_RESERVED, O_AWAITING, O_TRANSFERRED, O_DISPUTED)  # em andamento (bloqueiam apagar show e cancelar anúncio)
O_PAID = (O_AWAITING, O_TRANSFERRED, O_DISPUTED)  # valor retido na plataforma

BR_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem horário de verão desde 2019)

# ---------------------------------------------------------------- erros


class ResaleError(HTTPException):
    """Erro da revenda: `detail` em português e `code` em máquina (ex.: QTY_UNAVAILABLE) para o front."""

    def __init__(self, code: str, detail: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def conflict(code: str, detail: str) -> ResaleError:
    return ResaleError(code, detail, 409)


def forbidden(code: str, detail: str) -> ResaleError:
    return ResaleError(code, detail, 403)


def not_found(detail: str = "Não encontrado.") -> ResaleError:
    return ResaleError("NOT_FOUND", detail, 404)


# ---------------------------------------------------------------- relógio (injetável nos testes)

_override: Callable[[], datetime] | None = None


def utcnow() -> datetime:
    return _override() if _override else datetime.now(timezone.utc)


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Testes: troca o relógio (None volta ao real)."""
    global _override
    _override = fn


def aware(dt: datetime | None) -> datetime | None:
    """O SQLite devolve datetimes sem fuso: normaliza tudo para UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------- horário do show


def parse_show_time(text: str) -> tuple[int, int] | None:
    """'22h', '22h30', '22:00', 'às 21h' -> (hora, minuto); None se não der para ler."""
    m = re.search(r"(\d{1,2})\s*(?:h|:|hs)\s*(\d{2})?", text or "", re.I)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    return (hh, mm) if 0 <= hh <= 23 and 0 <= mm <= 59 else None


def show_start(day: date, time_text: str) -> datetime | None:
    """Início do show em UTC (data + horário no fuso de Brasília)."""
    hm = parse_show_time(time_text)
    if not hm:
        return None
    return datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=BR_TZ).astimezone(timezone.utc)


# ---------------------------------------------------------------- dinheiro (centavos inteiros)


def split_fee(gross_cents: int, fee_bps: int) -> tuple[int, int]:
    """(taxa, líquido do vendedor). Taxa em basis points sobre o bruto, arredondada para cima na metade (half-up)."""
    fee = (gross_cents * fee_bps + 5000) // 10000
    return fee, gross_cents - fee


# ---------------------------------------------------------------- cifra e hash de dados sensíveis


def is_dev_db() -> bool:
    """Banco SQLite = ambiente de desenvolvimento/teste."""
    from ..db import engine

    return engine.dialect.name == "sqlite"


def _require_keys() -> None:
    """Fora do desenvolvimento, CPF e códigos de ingresso só são cifrados com chaves PRÓPRIAS (não derivadas do JWT_SECRET)."""
    s = get_settings()
    if not is_dev_db() and not (s.resale_pii_key.strip() and s.resale_pepper.strip()):
        raise ResaleError("KEYS_MISSING", "A revenda de ingressos está indisponível: configure RESALE_PII_KEY e RESALE_PEPPER no servidor.", 503)


def _derive(label: str) -> bytes:
    return hashlib.sha256(f"{label}:{get_settings().jwt_secret}".encode()).digest()


def _fernet() -> Fernet:
    _require_keys()
    key = get_settings().resale_pii_key.strip()
    return Fernet(key.encode() if key else base64.urlsafe_b64encode(_derive("resale-pii")))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # chave trocada ou dado corrompido
        raise ResaleError("DECRYPT_FAILED", "Não foi possível ler o dado protegido.", 500) from exc


def pepper_hash(value: str) -> str:
    """HMAC-SHA256 com pepper: compara CPF e códigos de ingresso sem guardar o valor em claro."""
    _require_keys()
    pepper = get_settings().resale_pepper.encode() or _derive("resale-pepper")
    return hmac.new(pepper, value.encode(), hashlib.sha256).hexdigest()
