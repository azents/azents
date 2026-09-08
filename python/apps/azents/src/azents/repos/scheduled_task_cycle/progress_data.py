"""Detached Scheduled Task progress database-operation results."""

import dataclasses
from typing import Literal

from azents.core.external_channel_provider_effect import ProviderEffectPlan

type ScheduledTaskProgressPreparationStatus = Literal[
    "not_scheduled",
    "inactive",
    "prepared",
]
type ScheduledTaskProgressAdmissionStatus = Literal[
    "inactive",
    "superseded",
    "admitted",
]


@dataclasses.dataclass(frozen=True)
class ScheduledTaskTrackerEffect:
    """One prepared Scheduled Tracker provider mutation."""

    plan: ProviderEffectPlan
    expected_desired_revision: int
    part_ordinal: int


@dataclasses.dataclass(frozen=True)
class ScheduledTaskProgressPreparation:
    """One completed Scheduled progress preparation transaction."""

    status: ScheduledTaskProgressPreparationStatus
    cycle_id: str | None
    state_revision: int | None
    reply_plans: tuple[ProviderEffectPlan, ...]
    tracker: ScheduledTaskTrackerEffect | None


@dataclasses.dataclass(frozen=True)
class ScheduledTaskProgressAdmission:
    """One completed Scheduled progress effect-admission transaction."""

    status: ScheduledTaskProgressAdmissionStatus
    tracker_current: bool
