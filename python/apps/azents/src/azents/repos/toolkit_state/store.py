"""Typed DB-only Toolkit State handles."""

from collections.abc import Callable
from typing import Generic, TypeVar

from azents.core.toolkit_state import (
    ToolkitStateIdentity,
    ToolkitStateModelT,
    ToolkitStateSaved,
)
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert

SessionT_co = TypeVar(
    "SessionT_co", bound=ReadSession, default=WriteSession, covariant=True
)


class ToolkitStateHandle(Generic[ToolkitStateModelT, SessionT_co]):
    """State handle bound to a specific identity and Pydantic model."""

    def __init__(
        self,
        *,
        session: SessionT_co,
        repository: ToolkitStateRepository,
        identity: ToolkitStateIdentity,
        model_type: type[ToolkitStateModelT],
    ) -> None:
        """Create Toolkit State handle."""
        self._session = session
        self.repository = repository
        self.identity = identity
        self.model_type = model_type
        self.loaded_version: int | None = None

    @property
    def session(self) -> SessionT_co:
        """Return the captured capability without permitting reassignment."""
        return self._session

    async def load(
        self,
        default_factory: Callable[[], ToolkitStateModelT],
    ) -> ToolkitStateModelT:
        """Load stored state and return default_factory result when absent."""
        record = await self.repository.get(
            self.session,
            agent_id=self.identity.agent_id,
            session_id=self.identity.session_id,
            toolkit_namespace=self.identity.toolkit_namespace,
            state_name=self.identity.state_name,
        )
        if record is None:
            self.loaded_version = None
            return default_factory()
        self.loaded_version = record.version
        return self.model_type.model_validate(record.state_json)

    async def save(
        self: "ToolkitStateHandle[ToolkitStateModelT, WriteSession]",
        state: ToolkitStateModelT,
        *,
        max_retries: int = 3,
    ) -> ToolkitStateSaved:
        """Replace and store entire state."""
        return await self.update(
            lambda: state,
            lambda _: state,
            max_retries=max_retries,
        )

    async def update(
        self: "ToolkitStateHandle[ToolkitStateModelT, WriteSession]",
        default_factory: Callable[[], ToolkitStateModelT],
        mutator: Callable[[ToolkitStateModelT], ToolkitStateModelT],
        *,
        max_retries: int = 3,
    ) -> ToolkitStateSaved:
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

    async def _save(
        self: "ToolkitStateHandle[ToolkitStateModelT, WriteSession]",
        state: ToolkitStateModelT,
    ) -> ToolkitStateSaved:
        """Replace and store entire state."""
        record = await self.repository.save(
            self.session,
            ToolkitStateUpsert(
                agent_id=self.identity.agent_id,
                session_id=self.identity.session_id,
                toolkit_namespace=self.identity.toolkit_namespace,
                state_name=self.identity.state_name,
                state_json=state.model_dump(mode="json"),
                schema_version=state.schema_version,
                expected_version=self.loaded_version,
            ),
        )
        self.loaded_version = record.version
        return self._saved(record)

    @staticmethod
    def _saved(record: ToolkitStateRecord) -> ToolkitStateSaved:
        """Create storage result metadata."""
        return ToolkitStateSaved(
            id=record.id,
            version=record.version,
            schema_version=record.schema_version,
        )


class ToolkitStateStore(Generic[SessionT_co]):
    """Toolkit State handle factory."""

    def __init__(
        self,
        *,
        session: SessionT_co,
        repository: ToolkitStateRepository | None = None,
    ) -> None:
        """Create Toolkit State Store."""
        self._session = session
        self.repository = repository or ToolkitStateRepository()

    @property
    def session(self) -> SessionT_co:
        """Return the captured capability without permitting reassignment."""
        return self._session

    def handle(
        self,
        identity: ToolkitStateIdentity,
        model_type: type[ToolkitStateModelT],
    ) -> ToolkitStateHandle[ToolkitStateModelT, SessionT_co]:
        """Return typed handle for identity."""
        return ToolkitStateHandle(
            session=self.session,
            repository=self.repository,
            identity=identity,
            model_type=model_type,
        )
