"""LLM catalog repository tests."""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.rdb.models.llm_catalog import RDBLLMCatalogEntry, RDBLLMCatalogSnapshot
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import LLMCatalogEntryCreate

pytestmark = pytest.mark.asyncio


async def test_replace_current_snapshot_persists_snapshot_before_entries(
    rdb_session: AsyncSession,
) -> None:
    """Snapshot replacement should satisfy entry snapshot FK ordering."""
    repository = LLMCatalogRepository()
    catalog = await repository.ensure_system_catalog(
        rdb_session,
        provider=LLMProvider.OPENAI,
        lowerer_target=LLMCatalogLowererTarget.LITELLM,
    )

    snapshot_id = await repository.replace_current_snapshot(
        rdb_session,
        catalog=catalog,
        source_snapshot_id=None,
        entries=[
            LLMCatalogEntryCreate(
                provider=LLMProvider.OPENAI,
                provider_model_identifier="gpt-4o",
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier="gpt-4o",
                display_name="GPT-4o",
                normalized_capabilities=ModelCapabilities().model_dump(mode="json"),
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=None,
                publisher="openai",
                family="gpt",
                source_metadata=None,
                projection_metadata=None,
                hidden_reason=None,
            )
        ],
        diagnostics={"test": True},
    )

    await rdb_session.flush()
    snapshot_count = await rdb_session.scalar(
        sa.select(sa.func.count()).select_from(RDBLLMCatalogSnapshot)
    )
    entry_count = await rdb_session.scalar(
        sa.select(sa.func.count()).select_from(RDBLLMCatalogEntry)
    )

    assert snapshot_id is not None
    assert snapshot_count == 1
    assert entry_count == 1
