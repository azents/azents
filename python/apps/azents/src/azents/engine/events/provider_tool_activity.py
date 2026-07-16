"""Provider-neutral hosted-tool activity normalization."""

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from azents.engine.events.protocols import ProviderToolActivityProjection

ProviderToolActivityStatus: TypeAlias = Literal["running", "completed", "failed"]


class ProviderToolObservation(BaseModel):
    """One adapter-native provider-tool lifecycle observation."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: ProviderToolActivityStatus
    arguments: str | None = None


class ProviderToolActivityAccumulator:
    """Deduplicate and monotonically enrich provider-tool activity snapshots."""

    def __init__(self) -> None:
        self._snapshots: dict[str, ProviderToolObservation] = {}

    def observe(
        self,
        observation: ProviderToolObservation,
    ) -> ProviderToolActivityProjection | None:
        """Return a canonical projection when the public snapshot changed."""
        current = self._snapshots.get(observation.call_id)
        if current is None:
            snapshot = observation
        else:
            status = self._next_status(current.status, observation.status)
            snapshot = ProviderToolObservation(
                call_id=current.call_id,
                name=current.name,
                status=status,
                arguments=observation.arguments or current.arguments,
            )
            if snapshot == current:
                return None
        self._snapshots[observation.call_id] = snapshot
        return ProviderToolActivityProjection(
            call_id=snapshot.call_id,
            name=snapshot.name,
            status=snapshot.status,
            arguments=snapshot.arguments,
        )

    @staticmethod
    def _next_status(
        current: ProviderToolActivityStatus,
        observed: ProviderToolActivityStatus,
    ) -> ProviderToolActivityStatus:
        """Keep the first terminal state and prevent terminal regression."""
        if current in {"completed", "failed"}:
            return current
        return observed
