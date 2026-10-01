"""Explicit null/static source metadata collaborators for deterministic tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata import ModelMetadataService


class _StaticSourceRepository(ModelMetadataSourceRepository):
    """Return a supplied validated snapshot without database or network I/O."""

    def __init__(self, snapshot: ModelMetadataSourceSnapshot | None) -> None:
        self.snapshot = snapshot

    async def get_current(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> ModelMetadataSourceSnapshot | None:
        del session
        assert source_key == "genai_prices"
        return self.snapshot


@asynccontextmanager
async def _disconnected_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an explicitly disconnected session to the static repository."""
    async with AsyncSession() as session:
        yield session


def make_test_model_metadata_service(
    *,
    snapshot: ModelMetadataSourceSnapshot | None,
) -> ModelMetadataService:
    """Construct explicit static metadata instead of a global/default fallback."""
    return ModelMetadataService(
        session_manager=_disconnected_session,
        source_snapshot_repository=_StaticSourceRepository(snapshot),
    )
