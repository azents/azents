"""Runtime Terminal ticket codec tests."""

from datetime import UTC, datetime, timedelta

import pytest

from azents.services.runtime_terminal.data import (
    RuntimeTerminalResource,
    RuntimeTerminalTicketClaims,
)
from azents.services.runtime_terminal.ticket import (
    HmacRuntimeTerminalTicketCodec,
    RuntimeTerminalTicketInvalid,
)

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_ticket_round_trip_preserves_exact_resource_binding() -> None:
    codec = HmacRuntimeTerminalTicketCodec(b"s" * 32)
    claims = _claims()

    ticket = codec.encode(claims)

    assert codec.decode(ticket, now=_NOW) == claims


@pytest.mark.parametrize("mutation", ["suffix", "payload"])
def test_ticket_rejects_tampering(mutation: str) -> None:
    codec = HmacRuntimeTerminalTicketCodec(b"s" * 32)
    ticket = codec.encode(_claims())
    if mutation == "suffix":
        ticket = f"{ticket}x"
    else:
        ticket = f"x{ticket[1:]}"

    with pytest.raises(RuntimeTerminalTicketInvalid):
        codec.decode(ticket, now=_NOW)


def test_ticket_rejects_expiry() -> None:
    codec = HmacRuntimeTerminalTicketCodec(b"s" * 32)
    ticket = codec.encode(_claims())

    with pytest.raises(RuntimeTerminalTicketInvalid):
        codec.decode(ticket, now=_NOW + timedelta(seconds=30))


def _claims() -> RuntimeTerminalTicketClaims:
    return RuntimeTerminalTicketClaims(
        ticket_id="ticket-1",
        user_id="user-1",
        authentication_session_id="auth-session-1",
        workspace_id="workspace-1",
        resource=RuntimeTerminalResource(
            workspace_handle="workspace",
            agent_id="agent-1",
            session_id="session-1",
        ),
        intent="open_or_attach",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
    )
