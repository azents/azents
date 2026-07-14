"""Session-bound Toolkit State runtime abstraction."""

import dataclasses
from collections.abc import Callable
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.agent_execution import (
    AgentRunNotActiveError,
    AgentRunOwnershipLostError,
    AgentRunRepository,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert


@dataclasses.dataclass(frozen=True)
class ToolkitStateRunAuthority:
    """Durable Run identity required before a runtime-owned state write."""

    run_id: str
    owner_generation: int


class ToolkitStateRunAuthorityLostError(RuntimeError):
    """A stale Run attempted to mutate Session-bound Toolkit State."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Toolkit State write rejected for stale Run: {run_id}")
        self.run_id = run_id


class ToolkitStateIdentity(BaseModel):
    """Session-bound Toolkit State identity."""

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(min_length=1, description="Agent ID")
    session_id: str = Field(min_length=1, description="AgentSession ID")
    toolkit_namespace: str = Field(min_length=1, description="Toolkit namespace")
    state_name: str = Field(min_length=1, description="State name")

    @field_validator("agent_id", "session_id", "toolkit_namespace", "state_name")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """Deny identity string that is only whitespace."""
        if not value.strip():
            raise ValueError("Toolkit state identity fields must not be blank")
        return value


class ToolkitStateModel(BaseModel):
    """Common base model for Toolkit State payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, description="Payload schema version")


class SavedToolkitState(BaseModel):
    """Stored Toolkit State metadata."""

    id: str = Field(description="Toolkit State ID")
    version: int = Field(description="Row version")
    schema_version: int = Field(description="Payload schema version")


StateT = TypeVar("StateT", bound=ToolkitStateModel)


class ToolkitStateHandle(Generic[StateT]):
    """State handle bound to specific identity and Pydantic model."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: ToolkitStateRepository,
        identity: ToolkitStateIdentity,
        model_type: type[StateT],
    ) -> None:
        """Create Toolkit State handle."""
        self._session = session
        self._repository = repository
        self._identity = identity
        self._model_type = model_type
        self._loaded_version: int | None = None

    async def load(self, default_factory: Callable[[], StateT]) -> StateT:
        """Load stored state and return default_factory result when absent."""
        record = await self._repository.get(
            self._session,
            agent_id=self._identity.agent_id,
            session_id=self._identity.session_id,
            toolkit_namespace=self._identity.toolkit_namespace,
            state_name=self._identity.state_name,
        )
        if record is None:
            self._loaded_version = None
            return default_factory()
        self._loaded_version = record.version
        return self._model_type.model_validate(record.state_json)

    async def save(self, state: StateT, *, max_retries: int = 3) -> SavedToolkitState:
        """Replace and store entire state."""
        return await self.update(
            lambda: state,
            lambda _: state,
            max_retries=max_retries,
        )

    async def update(
        self,
        default_factory: Callable[[], StateT],
        mutator: Callable[[StateT], StateT],
        *,
        max_retries: int = 3,
    ) -> SavedToolkitState:
        """Apply mutator to latest state and store with optimistic-lock retry."""
        if max_retries < 1:
            raise ValueError("max_retries must be greater than zero")

        last_error: ToolkitStateConflictError | None = None
        for _ in range(max_retries):
            current = await self.load(default_factory=default_factory)
            updated = mutator(current)
            try:
                return await self._save(updated)
            except ToolkitStateConflictError as exc:
                last_error = exc

        if last_error is None:
            raise ToolkitStateConflictError("Toolkit State update failed")
        raise last_error

    async def _save(self, state: StateT) -> SavedToolkitState:
        """Replace and store entire state."""
        record = await self._repository.save(
            self._session,
            ToolkitStateUpsert(
                agent_id=self._identity.agent_id,
                session_id=self._identity.session_id,
                toolkit_namespace=self._identity.toolkit_namespace,
                state_name=self._identity.state_name,
                state_json=state.model_dump(mode="json"),
                schema_version=state.schema_version,
                expected_version=self._loaded_version,
            ),
        )
        self._loaded_version = record.version
        return self._saved(record)

    def _saved(self, record: ToolkitStateRecord) -> SavedToolkitState:
        """Create storage result metadata."""
        return SavedToolkitState(
            id=record.id,
            version=record.version,
            schema_version=record.schema_version,
        )


class RunFencedToolkitStateHandle(ToolkitStateHandle[StateT]):
    """Toolkit State handle that rejects writes from a stale Session Run."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: ToolkitStateRepository,
        identity: ToolkitStateIdentity,
        model_type: type[StateT],
        run_authority: ToolkitStateRunAuthority,
        agent_run_repository: AgentRunRepository,
        agent_session_repository: AgentSessionRepository,
    ) -> None:
        """Create a handle with explicit durable authority dependencies."""
        super().__init__(
            session=session,
            repository=repository,
            identity=identity,
            model_type=model_type,
        )
        self._run_authority = run_authority
        self._agent_run_repository = agent_run_repository
        self._agent_session_repository = agent_session_repository

    async def _save(self, state: StateT) -> SavedToolkitState:
        """Fence and save within the same short database transaction."""
        await self._validate_run_authority()
        return await super()._save(state)

    async def _validate_run_authority(self) -> None:
        """Lock the Session and exact Run before the state row is mutated."""
        agent_session = await self._agent_session_repository.lock_by_id(
            self._session,
            self._identity.session_id,
        )
        if (
            agent_session is None
            or agent_session.owner_generation != self._run_authority.owner_generation
        ):
            raise ToolkitStateRunAuthorityLostError(self._run_authority.run_id)
        try:
            # Keep the exact Run row locked through Toolkit State persistence.
            # A plain active-run SELECT allows a concurrent terminal UPDATE to
            # commit first and the stale state write to land after terminality.
            await self._agent_run_repository.lock_active_owner(
                self._session,
                run_id=self._run_authority.run_id,
                session_id=self._identity.session_id,
                owner_generation=self._run_authority.owner_generation,
            )
        except AgentRunNotActiveError, AgentRunOwnershipLostError, ValueError:
            raise ToolkitStateRunAuthorityLostError(
                self._run_authority.run_id
            ) from None


class ToolkitStateStore:
    """Toolkit State handle factory."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: ToolkitStateRepository | None = None,
    ) -> None:
        """Create Toolkit State Store."""
        self._session = session
        self._repository = repository or ToolkitStateRepository()

    def handle(
        self,
        identity: ToolkitStateIdentity,
        model_type: type[StateT],
    ) -> ToolkitStateHandle[StateT]:
        """Return typed handle for identity."""
        return ToolkitStateHandle(
            session=self._session,
            repository=self._repository,
            identity=identity,
            model_type=model_type,
        )


class RunFencedToolkitStateStore:
    """Run-fenced Toolkit State handle factory with explicit collaborators."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: ToolkitStateRepository,
        run_authority: ToolkitStateRunAuthority,
        agent_run_repository: AgentRunRepository,
        agent_session_repository: AgentSessionRepository,
    ) -> None:
        """Create a run-fenced Toolkit State store."""
        self._session = session
        self._repository = repository
        self._run_authority = run_authority
        self._agent_run_repository = agent_run_repository
        self._agent_session_repository = agent_session_repository

    def handle(
        self,
        identity: ToolkitStateIdentity,
        model_type: type[StateT],
    ) -> RunFencedToolkitStateHandle[StateT]:
        """Return a typed handle fenced by the configured Run authority."""
        return RunFencedToolkitStateHandle(
            session=self._session,
            repository=self._repository,
            identity=identity,
            model_type=model_type,
            run_authority=self._run_authority,
            agent_run_repository=self._agent_run_repository,
            agent_session_repository=self._agent_session_repository,
        )
