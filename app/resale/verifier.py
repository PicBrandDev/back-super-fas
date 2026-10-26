"""Verificador do ingresso na ticketeira terceira (plugável). Hoje só há o stub: devolve 'unknown' e a prova fica
inteira para a revisão manual do admin. Quando a integração existir, implemente `TicketVerifier` e troque `get_verifier()`."""

from dataclasses import dataclass
from typing import Protocol

from .. import models as m


@dataclass
class VerifyResult:
    status: str  # unknown | valid | invalid | already_listed
    detail: str = ""


class TicketVerifier(Protocol):
    def verify(self, event: m.Event, ticket_label: str, code: str, seller: m.User) -> VerifyResult: ...


class StubVerifier:
    def verify(self, event: m.Event, ticket_label: str, code: str, seller: m.User) -> VerifyResult:
        return VerifyResult("unknown", "Sem integração com a ticketeira: conferência manual.")


def get_verifier() -> TicketVerifier:
    return StubVerifier()


def summarize(results: list[VerifyResult]) -> VerifyResult:
    """Resultado do anúncio: o pior dos códigos (invalid > already_listed > unknown > valid)."""
    for bad in ("invalid", "already_listed", "unknown"):
        hit = next((r for r in results if r.status == bad), None)
        if hit:
            return hit
    return VerifyResult("valid", "")
