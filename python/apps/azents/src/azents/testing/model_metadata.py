"""Explicit null/static source metadata collaborators for deterministic tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.llm_catalog import LiteLLMSourceSnapshotRepository
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
from azents.services.model_metadata import ModelMetadataService


class _StaticSourceSnapshotRepository(LiteLLMSourceSnapshotRepository):
    """Return a supplied validated snapshot without database or network I/O."""

    def __init__(self, snapshot: LiteLLMSourceSnapshot | None) -> None:
        self.snapshot = snapshot

    async def get_latest_authoritative(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> LiteLLMSourceSnapshot | None:
        del session
        assert source_key == "litellm_model_cost"
        return self.snapshot


@asynccontextmanager
async def _disconnected_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an explicitly disconnected session to the static repository."""
    async with AsyncSession() as session:
        yield session


def make_test_model_metadata_service(
    *,
    snapshot: LiteLLMSourceSnapshot | None,
) -> ModelMetadataService:
    """Construct explicit static metadata instead of a global/default fallback.

    :param snapshot: supplied validated source fixture or an absent source
    :returns: source metadata service with no database or remote fetch capability
    """
    return ModelMetadataService(
        session_manager=_disconnected_session,
        source_snapshot_repository=_StaticSourceSnapshotRepository(snapshot),
    )
