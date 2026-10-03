"""Atomic catalog-operation and detached-boundary regressions without database I/O."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.repos.image_generation_catalog_operations import (
    ImageGenerationCatalogOperationsRepository,
)
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    CatalogProjectionProvenance,
    ImageGenerationCatalogPublication,
    IntegrationCatalogSyncClaim,
    LLMCatalog,
)
from azents.repos.llm_catalog_operations import (
    CatalogAttemptFailure,
    CatalogPublicationSucceeded,
    CatalogPublicationSuperseded,
    LLMCatalogOperationsRepository,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegration

_NOW = datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC)


class _TransactionProbe:
    """Expose each transaction lifetime and its completed outcome."""

    def __init__(self) -> None:
        self.session: AsyncSession = AsyncMock(spec=AsyncSession)
        self.active = False
        self.commits = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        assert not self.active
        self.active = True
        try:
            yield self.session
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1
        finally:
            self.active = False


def _catalog(purpose: LLMCatalogPurpose) -> LLMCatalog:
    """Build purpose-specific immutable catalog authority."""
    return LLMCatalog(
        id="catalog",
        scope=LLMCatalogScope.INTEGRATION,
        provider=LLMProvider.OPENAI,
        purpose=purpose,
        provider_integration_id="integration",
        current_snapshot_id="previous",
        latest_attempt_id="attempt",
    )


def _claim() -> IntegrationCatalogSyncClaim:
    """Capture the exact snapshot and configuration-generation publication fence."""
    return IntegrationCatalogSyncClaim(
        attempt_id="attempt",
        expected_current_snapshot_id="previous",
        catalog_configuration_version=4,
    )


def _provenance() -> CatalogProjectionProvenance:
    """Build captured projection evidence without requiring a current system source."""
    return CatalogProjectionProvenance(
        source_snapshot_id=None,
        projection_schema_version="2",
        runtime_profile_resolver_revision="resolver",
        pydantic_ai_version="fixture",
        genai_prices_version=None,
        projection_fingerprint="fingerprint",
    )


@pytest.mark.parametrize(
    ("image", "purpose", "source_key"),
    [
        (False, LLMCatalogPurpose.CONVERSATION, "litellm_catalog"),
        (
            True,
            LLMCatalogPurpose.IMAGE_GENERATION,
            "openai_models_list:image_generation",
        ),
    ],
)
async def test_claim_composes_catalog_creation_and_attempt_in_one_transaction(
    image: bool,
    purpose: LLMCatalogPurpose,
    source_key: str,
) -> None:
    """Claim operations preserve purpose/source identity and commit before returning."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    integrations = AsyncMock(spec=LLMProviderIntegrationRepository)
    catalogs.ensure_integration_catalog.return_value = _catalog(purpose)
    catalogs.begin_integration_attempt.return_value = _claim()
    operations = (
        ImageGenerationCatalogOperationsRepository(manager, catalogs, integrations)
        if image
        else LLMCatalogOperationsRepository(manager, catalogs, integrations)
    )
    result = await operations.begin_attempt(
        integration_id="integration",
        provider=LLMProvider.OPENAI,
        workspace_id="workspace",
        started_at=_NOW,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    assert result.claim == _claim()
    assert result.catalog.purpose is purpose
    assert manager.commits == 1
    assert manager.rollbacks == 0
    assert manager.active is False
    creation = catalogs.ensure_integration_catalog.await_args
    attempt = catalogs.begin_integration_attempt.await_args
    assert creation is not None and attempt is not None
    assert creation.args[0] is attempt.args[0] is manager.session
    assert creation.kwargs["purpose"] is purpose
    assert attempt.kwargs["source_key"] == source_key


async def test_conversation_publication_keeps_all_writes_inside_one_transaction() -> (
    None
):
    """Candidate, fenced pointer CAS and attempt success share one completed commit."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.lock_catalog_for_attempt_completion.return_value = "attempt"
    catalogs.create_candidate_snapshot.return_value = "candidate"
    catalogs.publish_candidate_snapshot.return_value = "published"
    operations = LLMCatalogOperationsRepository(
        manager, catalogs, AsyncMock(spec=LLMProviderIntegrationRepository)
    )
    result = await operations.publish(
        catalog=_catalog(LLMCatalogPurpose.CONVERSATION),
        claim=_claim(),
        entries=[],
        provenance=_provenance(),
        candidate_diagnostics={"candidate": "captured"},
        attempt_diagnostics={"attempt": "captured"},
        fetched_count=0,
        skipped_count=0,
        finished_at=_NOW,
    )
    assert result == CatalogPublicationSucceeded("published", 0, 0)
    assert manager.commits == 1
    assert manager.active is False
    for method in (
        catalogs.lock_catalog_for_attempt_completion,
        catalogs.create_candidate_snapshot,
        catalogs.publish_candidate_snapshot,
        catalogs.mark_attempt_succeeded,
    ):
        assert method.await_args is not None
        assert method.await_args.args[0] is manager.session
    publication = catalogs.publish_candidate_snapshot.await_args
    assert publication is not None
    assert publication.kwargs["expected_current_snapshot_id"] == "previous"
    assert publication.kwargs["expected_catalog_configuration_version"] == 4
    assert publication.kwargs["expected_projection_fingerprint"] == "fingerprint"
    assert publication.kwargs["fence_latest_attempt"] is True
    assert publication.kwargs["expected_latest_attempt_id"] == "attempt"


async def test_superseded_conversation_attempt_never_creates_a_candidate() -> None:
    """A newer attempt leaves prior snapshot authority untouched."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.lock_catalog_for_attempt_completion.return_value = "newer"
    operations = LLMCatalogOperationsRepository(
        manager, catalogs, AsyncMock(spec=LLMProviderIntegrationRepository)
    )
    result = await operations.publish(
        catalog=_catalog(LLMCatalogPurpose.CONVERSATION),
        claim=_claim(),
        entries=[],
        provenance=_provenance(),
        candidate_diagnostics=None,
        attempt_diagnostics=None,
        fetched_count=0,
        skipped_count=0,
        finished_at=_NOW,
    )
    assert result == CatalogPublicationSuperseded("newer")
    catalogs.create_candidate_snapshot.assert_not_awaited()
    catalogs.publish_candidate_snapshot.assert_not_awaited()
    catalogs.mark_attempt_succeeded.assert_not_awaited()
    assert manager.active is False


async def test_publication_failure_rolls_back_before_separate_failure_record() -> None:
    """Unexpected publication failure cannot turn into a successful partial commit."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.lock_catalog_for_attempt_completion.return_value = "attempt"
    catalogs.create_candidate_snapshot.return_value = "candidate"
    catalogs.publish_candidate_snapshot.return_value = "published"
    catalogs.mark_attempt_succeeded.side_effect = RuntimeError("success write failed")
    operations = LLMCatalogOperationsRepository(
        manager, catalogs, AsyncMock(spec=LLMProviderIntegrationRepository)
    )
    with pytest.raises(RuntimeError, match="success write failed"):
        await operations.publish(
            catalog=_catalog(LLMCatalogPurpose.CONVERSATION),
            claim=_claim(),
            entries=[],
            provenance=_provenance(),
            candidate_diagnostics=None,
            attempt_diagnostics=None,
            fetched_count=0,
            skipped_count=0,
            finished_at=_NOW,
        )
    assert manager.active is False
    assert manager.rollbacks == 1
    assert manager.commits == 0
    catalogs.mark_attempt_failed.assert_not_awaited()
    await operations.fail_attempt(
        CatalogAttemptFailure(
            attempt_id="attempt",
            finished_at=_NOW,
            failure_code="RuntimeError",
            failure_message="success write failed",
            action_hint="Retry",
            diagnostics={"failure_category": "catalog_service_failure"},
        )
    )
    assert manager.commits == 1
    assert manager.active is False
    catalogs.mark_attempt_failed.assert_awaited_once()


async def test_superseded_image_publication_finalizes_failure_atomically() -> None:
    """Image generation fencing and its failure metadata use the same transaction."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    catalogs.replace_current_image_generation_snapshot.return_value = (
        ImageGenerationCatalogPublication(
            snapshot_id=None,
            superseding_attempt_id="newer",
            current_catalog_configuration_version=5,
        )
    )
    operations = ImageGenerationCatalogOperationsRepository(
        manager, catalogs, AsyncMock(spec=LLMProviderIntegrationRepository)
    )
    result = await operations.publish(
        catalog=_catalog(LLMCatalogPurpose.IMAGE_GENERATION),
        attempt_id="attempt",
        entries=[],
        candidate_diagnostics=None,
        attempt_diagnostics=None,
        fetched_count=0,
        finished_at=_NOW,
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
    )
    assert result.snapshot_id is None
    replacement = catalogs.replace_current_image_generation_snapshot.await_args
    failure = catalogs.mark_attempt_failed.await_args
    assert replacement is not None and failure is not None
    assert replacement.args[0] is failure.args[0] is manager.session
    assert failure.kwargs["failure_code"] == "CatalogSyncSuperseded"
    assert failure.kwargs["diagnostics"]["automatic_retry_blocked"] is False
    catalogs.mark_attempt_succeeded.assert_not_awaited()
    assert manager.commits == 1
    assert manager.active is False


async def test_default_only_image_read_never_creates_discovery_catalog() -> None:
    """OAuth default-only availability needs local integration state, not discovery."""
    manager = _TransactionProbe()
    catalogs = AsyncMock(spec=LLMCatalogRepository)
    integrations = AsyncMock(spec=LLMProviderIntegrationRepository)
    integrations.get_by_id.return_value = LLMProviderIntegration(
        id="integration",
        workspace_id="workspace",
        provider=LLMProvider.CHATGPT_OAUTH,
        name="Default-only",
        config=None,
        enabled=True,
        created_at=_NOW,
        updated_at=_NOW,
        catalog_configuration_version=1,
    )
    operations = ImageGenerationCatalogOperationsRepository(
        manager, catalogs, integrations
    )
    result = await operations.read(
        integration_id="integration", workspace_id="workspace"
    )
    assert result is not None
    assert result.page is None
    catalogs.ensure_integration_catalog.assert_not_awaited()
    catalogs.list_image_generation_entries_by_integration.assert_not_awaited()
    assert manager.commits == 1
    assert manager.active is False
