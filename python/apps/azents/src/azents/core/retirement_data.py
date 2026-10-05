"""Detached evidence from completed root-retirement database operations."""

import dataclasses
import datetime

from azents.core.enums import AgentSessionProductMode, AgentSessionStatus
from azents.core.external_channel_provider_effect import ProviderEffectPlan


@dataclasses.dataclass(frozen=True)
class RetirementRoot:
    """Descriptive root identity without a database handle."""

    id: str
    status: AgentSessionStatus
    product_mode: AgentSessionProductMode | None


@dataclasses.dataclass(frozen=True)
class RootRetirement:
    """Committed archive and durable stop evidence for external effects."""

    retired: bool
    archived: bool
    stop_session_ids: tuple[str, ...]
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclasses.dataclass(frozen=True)
class RetirementBlob:
    """Direct-owned blob snapshot for post-commit object-store deletion."""

    id: str
    object_key: str
    blob_deleted_at: datetime.datetime | None
