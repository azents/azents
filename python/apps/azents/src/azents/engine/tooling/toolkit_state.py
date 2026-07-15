"""Session-bound Toolkit State runtime abstraction."""

from collections.abc import Callable
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert


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
        self.session = session
        self.repository = repository
        self._identity = identity
        self._model_type = model_type
        self._loaded_version: int | None = None

    async def load(self, default_factory: Callable[[], StateT]) -> StateT:
        """Load stored state and return default_factory result when absent."""
        record = await self.repository.get(
            self.session,
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
        record = await self.repository.save(
            self.session,
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


class ToolkitStateStore:
    """Toolkit State handle factory."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: ToolkitStateRepository | None = None,
    ) -> None:
        """Create Toolkit State Store."""
        self.session = session
        self.repository = repository or ToolkitStateRepository()

    def handle(
        self,
        identity: ToolkitStateIdentity,
        model_type: type[StateT],
    ) -> ToolkitStateHandle[StateT]:
        """Return typed handle for identity."""
        return ToolkitStateHandle(
            session=self.session,
            repository=self.repository,
            identity=identity,
            model_type=model_type,
        )
