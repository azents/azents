"""Detached terminal Run delivery outcomes."""

import dataclasses
from enum import StrEnum


class TerminalDeliveryDisposition(StrEnum):
    """Outcome of one terminal Run's direct-parent delivery attempt."""

    ENQUEUED = "enqueued"
    SUPPRESSED = "suppressed"
    ALREADY_FINALIZED = "already_finalized"
    INELIGIBLE = "ineligible"


@dataclasses.dataclass(frozen=True)
class TerminalFinalizationOutcome:
    """Structured terminal Run finalization outcome."""

    run_id: str
    disposition: TerminalDeliveryDisposition
    mailbox_item_id: str | None = None
