"""Binding-specific External Channel Work Toolkit State."""

import datetime
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    ExternalChannelWorkTask,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import RDBExternalChannelBinding
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateUpsert

EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE = "external_channel"
CHANNEL_WORK_STATE_NAME_PREFIX = "channel_work:"
CHANNEL_WORK_STATE_SCHEMA_VERSION = 1


class ChannelWorkProjectionPartState(BaseModel):
    """Current provider projection state for one ordered Work part."""

    model_config = ConfigDict(extra="forbid")

    part_ordinal: int = Field(ge=0)
    desired_progress_revision: int = Field(ge=0)
    status: ExternalChannelWorkProjectionStatus
    provider_message_key: str | None


class ChannelWorkState(BaseModel):
    """Current or latest Channel Work cycle stored in Toolkit State."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = CHANNEL_WORK_STATE_SCHEMA_VERSION
    binding_id: str = Field(min_length=1)
    work_cycle_id: str = Field(min_length=1)
    status: ExternalChannelWorkStatus
    title: str | None
    tasks: list[ExternalChannelWorkTask]
    state_revision: int = Field(ge=1)
    desired_progress_revision: int = Field(ge=0)
    desired_progress: ExternalChannelDesiredProgress | None
    finished_at: datetime.datetime | None
    projection_parts: list[ChannelWorkProjectionPartState]

    @model_validator(mode="after")
    def validate_projection_parts(self) -> "ChannelWorkState":
        """Require one deterministic current projection per part ordinal."""
        ordinals = [part.part_ordinal for part in self.projection_parts]
        if ordinals != sorted(ordinals):
            raise ValueError("Channel Work projection parts must be ordered.")
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("Channel Work projection part ordinals must be unique.")
        if (
            self.status is ExternalChannelWorkStatus.ACTIVE
            and self.finished_at is not None
        ):
            raise ValueError("Active Channel Work cannot have a finished timestamp.")
        if (
            self.status is ExternalChannelWorkStatus.FINISHED
            and self.finished_at is None
        ):
            raise ValueError("Finished Channel Work requires a finished timestamp.")
        return self


ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class ChannelWorkStateMutation(Generic[ResultT]):
    """One whole-state replacement and its transaction-local result."""

    state: ChannelWorkState
    result: ResultT
    changed: bool = True


def channel_work_state_name(binding_id: str) -> str:
    """Return the stable binding-derived Toolkit State name."""
    if not binding_id:
        raise ValueError("External Channel binding ID is required.")
    return f"{CHANNEL_WORK_STATE_NAME_PREFIX}{binding_id}"


class ExternalChannelWorkStateStore:
    """Load and mutate binding-specific Work through Toolkit State CAS."""

    def __init__(
        self,
        repository: ToolkitStateRepository | None = None,
    ) -> None:
        """Create the state store."""
        self.repository = repository or ToolkitStateRepository()

    async def load(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
    ) -> ChannelWorkState | None:
        """Load one binding's current or latest Work state."""
        await self._validate_binding_ownership(
            session,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding_id,
        )
        record = await self.repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
            state_name=channel_work_state_name(binding_id),
        )
        if record is None:
            return None
        return self._validate_state(
            record.state_json,
            binding_id=binding_id,
            schema_version=record.schema_version,
        )

    async def update(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        default_factory: Callable[[], ChannelWorkState],
        mutator: Callable[[ChannelWorkState], ChannelWorkStateMutation[ResultT]],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[ResultT]:
        """Apply one pure mutation to the latest state with bounded CAS retry."""
        if max_retries < 1:
            raise ValueError("max_retries must be greater than zero")
        await self._validate_binding_ownership(
            session,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding_id,
        )
        last_error: ToolkitStateConflictError | None = None
        for _ in range(max_retries):
            record = await self.repository.get(
                session,
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
                state_name=channel_work_state_name(binding_id),
            )
            if record is None:
                current = default_factory()
                expected_version = None
            else:
                current = self._validate_state(
                    record.state_json,
                    binding_id=binding_id,
                    schema_version=record.schema_version,
                )
                expected_version = record.version
            mutation = mutator(current)
            if mutation.state.binding_id != binding_id:
                raise ValueError("Channel Work state binding identity changed.")
            if not mutation.changed:
                return mutation
            try:
                await self.repository.save(
                    session,
                    ToolkitStateUpsert(
                        agent_id=agent_id,
                        session_id=session_id,
                        toolkit_namespace=EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
                        state_name=channel_work_state_name(binding_id),
                        state_json=mutation.state.model_dump(mode="json"),
                        schema_version=mutation.state.schema_version,
                        expected_version=expected_version,
                    ),
                )
            except ToolkitStateConflictError as error:
                last_error = error
                continue
            return mutation
        if last_error is None:
            raise ToolkitStateConflictError("Channel Work state update failed")
        raise last_error

    async def update_existing(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        mutator: Callable[[ChannelWorkState], ChannelWorkStateMutation[ResultT]],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[ResultT] | None:
        """Apply one pure mutation without creating an absent Work state."""
        if max_retries < 1:
            raise ValueError("max_retries must be greater than zero")
        await self._validate_binding_ownership(
            session,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding_id,
        )
        last_error: ToolkitStateConflictError | None = None
        for _ in range(max_retries):
            record = await self.repository.get(
                session,
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
                state_name=channel_work_state_name(binding_id),
            )
            if record is None:
                return None
            current = self._validate_state(
                record.state_json,
                binding_id=binding_id,
                schema_version=record.schema_version,
            )
            mutation = mutator(current)
            if mutation.state.binding_id != binding_id:
                raise ValueError("Channel Work state binding identity changed.")
            if not mutation.changed:
                return mutation
            try:
                await self.repository.save(
                    session,
                    ToolkitStateUpsert(
                        agent_id=agent_id,
                        session_id=session_id,
                        toolkit_namespace=EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
                        state_name=channel_work_state_name(binding_id),
                        state_json=mutation.state.model_dump(mode="json"),
                        schema_version=mutation.state.schema_version,
                        expected_version=record.version,
                    ),
                )
            except ToolkitStateConflictError as error:
                last_error = error
                continue
            return mutation
        if last_error is None:
            raise ToolkitStateConflictError("Channel Work state update failed")
        raise last_error

    async def list_for_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
    ) -> dict[str, ChannelWorkState]:
        """Load every binding Work state for one AgentSession."""
        rows = list(
            await session.scalars(
                sa.select(RDBToolkitState)
                .where(
                    RDBToolkitState.agent_id == agent_id,
                    RDBToolkitState.session_id == session_id,
                    RDBToolkitState.toolkit_namespace
                    == EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
                    RDBToolkitState.state_name.like(
                        f"{CHANNEL_WORK_STATE_NAME_PREFIX}%"
                    ),
                )
                .order_by(RDBToolkitState.state_name)
            )
        )
        states: dict[str, ChannelWorkState] = {}
        for row in rows:
            binding_id = row.state_name.removeprefix(CHANNEL_WORK_STATE_NAME_PREFIX)
            if not binding_id:
                raise ValueError("Channel Work Toolkit State has no binding identity.")
            states[binding_id] = self._validate_state(
                row.state_json,
                binding_id=binding_id,
                schema_version=row.schema_version,
            )
        return states

    async def list_for_sessions(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> list[ChannelWorkState]:
        """Load every External Channel Work state in a Session tree."""
        if not session_ids:
            return []
        rows = list(
            await session.scalars(
                sa.select(RDBToolkitState)
                .where(
                    RDBToolkitState.session_id.in_(session_ids),
                    RDBToolkitState.toolkit_namespace
                    == EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
                    RDBToolkitState.state_name.like(
                        f"{CHANNEL_WORK_STATE_NAME_PREFIX}%"
                    ),
                )
                .order_by(RDBToolkitState.session_id, RDBToolkitState.state_name)
            )
        )
        return [
            self._validate_state(
                row.state_json,
                binding_id=row.state_name.removeprefix(CHANNEL_WORK_STATE_NAME_PREFIX),
                schema_version=row.schema_version,
            )
            for row in rows
        ]

    async def delete_for_sessions(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> int:
        """Delete External Channel Work state for a Session tree."""
        if not session_ids:
            return 0
        result = await session.execute(
            sa.delete(RDBToolkitState)
            .where(
                RDBToolkitState.session_id.in_(session_ids),
                RDBToolkitState.toolkit_namespace
                == EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
                RDBToolkitState.state_name.like(f"{CHANNEL_WORK_STATE_NAME_PREFIX}%"),
            )
            .returning(RDBToolkitState.id)
        )
        return len(result.scalars().all())

    async def _validate_binding_ownership(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
    ) -> None:
        """Require the requested Toolkit State identity to match its binding."""
        owned_binding_id = await session.scalar(
            sa.select(RDBExternalChannelBinding.id)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
            )
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.agent_session_id == session_id,
                RDBAgentSession.agent_id == agent_id,
            )
        )
        if owned_binding_id is None:
            raise ValueError(
                "External Channel Work identity does not match binding ownership."
            )

    def _validate_state(
        self,
        state_json: dict[str, object],
        *,
        binding_id: str,
        schema_version: int,
    ) -> ChannelWorkState:
        """Validate payload schema and binding-derived identity."""
        if schema_version != CHANNEL_WORK_STATE_SCHEMA_VERSION:
            raise ValueError("Unsupported Channel Work Toolkit State schema version.")
        state = ChannelWorkState.model_validate(state_json)
        if state.binding_id != binding_id:
            raise ValueError("Channel Work Toolkit State binding is inconsistent.")
        return state
