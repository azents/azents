"""Whole-claim supervision covers blocked setup and replacement-candidate handoff."""

import asyncio
import dataclasses
import datetime
import json
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.result import Success

from azents.core.active_model_capabilities import (
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.config import Config
from azents.core.enums import LLMProvider
from azents.core.historical_memory_consolidation import ConsolidationUnitKey
from azents.core.model_catalog_identity import catalog_source_keys
from azents.core.model_catalog_source import decode_catalog_source
from azents.engine.events.openai_responses import OpenAIResponsesWebSocketConnection
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.providers.model_factory import ProviderModelFactory
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
)
from azents.engine.run.resolve import ResolvedModelCandidateRuntime
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationUnit,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.agent import AgentRepository
from azents.repos.engine_read import EngineModelReadRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationClaim,
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationRepository,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import CapturedContextSource
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.historical_memory import consolidation_job as jobs
from azents.services.historical_memory.consolidation_host import (
    ConsolidationIterationHost,
)
from azents.services.model_metadata import ModelMetadataService
from azents.testing.consolidation import seed_consolidation_corpus
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)
from azents.testing.model_stream import make_test_model_stream_watchdog


class _Clock:
    def __init__(self) -> None:
        self.requests: asyncio.Queue[float] = asyncio.Queue()
        self.ticks: asyncio.Queue[None] = asyncio.Queue()

    def time(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep(self, delay: float) -> None:
        await self.requests.put(delay)
        await self.ticks.get()


@dataclasses.dataclass
class _BlockedResolution:
    block_at: int
    calls: int = dataclasses.field(init=False, default=0)
    started: asyncio.Event = dataclasses.field(
        init=False, default_factory=asyncio.Event
    )
    stopped: asyncio.Event = dataclasses.field(
        init=False, default_factory=asyncio.Event
    )
    release: asyncio.Event = dataclasses.field(
        init=False, default_factory=asyncio.Event
    )

    async def resolve(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        selection: AgentModelSelection,
        settings: SelectableModelSettings,
        context_source: CapturedContextSource | None,
        model_read_repository: EngineModelReadRepository,
        runtime_token_resolver: EngineRuntimeTokenResolver,
        model_metadata_service: ModelMetadataService,
    ) -> Success[ResolvedModelCandidateRuntime]:
        self.calls += 1
        if self.calls == self.block_at:
            self.started.set()
            try:
                await self.release.wait()
            finally:
                self.stopped.set()
        return Success(
            ResolvedModelCandidateRuntime(
                provider=selection.provider,
                provider_integration_id=selection.llm_provider_integration_id,
                model=selection.model_identifier,
                credential_kwargs={"api_key": "synthetic-unused"},
                effective_input_tokens=128000,
            )
        )


class _Client:
    def __init__(self) -> None:
        self.closed = False

    async def create_response(self, **kwargs: object) -> object:
        raise AssertionError("Blocked preparation must never dispatch a model request.")

    async def connect_websocket(self) -> OpenAIResponsesWebSocketConnection:
        raise AssertionError(
            "Blocked preparation must never connect a model transport."
        )

    async def close(self) -> None:
        self.closed = True


@dataclasses.dataclass(frozen=True)
class _Harness:
    service: jobs.HistoricalMemoryConsolidationService
    key: ConsolidationUnitKey
    block: _BlockedResolution
    clock: _Clock
    claims: list[ConsolidationClaim]
    clients: list[_Client]
    hosts: list[ConsolidationIterationHost]


async def _harness(
    manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    *,
    block_at: int,
    deadline_seconds: float | None,
) -> _Harness:
    corpus = await seed_consolidation_corpus(manager)
    async with manager() as session:
        integration = RDBLLMProviderIntegration(
            workspace_id=corpus.team.workspace_id,
            provider=LLMProvider.OPENAI,
            name="Synthetic claimed route",
            encrypted_credentials="unused",
            config=None,
        )
        session.write_session.add(integration)
        await session.write_session.flush()
        main = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="main-not-permitted"
        )
        primary = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-first"
        )
        secondary = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="lightweight-second"
        )
        options = make_test_selectable_model_option_dicts(
            model_selection=main, lightweight_model_selection=primary
        )
        second_options = make_test_selectable_model_option_dicts(
            model_selection=main, lightweight_model_selection=secondary
        )
        first = options[1]["candidates"]
        second = second_options[1]["candidates"]
        assert isinstance(first, list) and isinstance(second, list)
        options[1]["candidates"] = [*first, *second]
        agent = await session.read_session.get(RDBAgent, corpus.team.agent_id)
        assert agent is not None
        agent.model_selection = main
        agent.selectable_model_options = options
        agent.lightweight_model_selection = primary
    claims: list[ConsolidationClaim] = []
    original_claim = ConsolidationOwnershipRepository.claim

    async def capture_claim(
        self: ConsolidationOwnershipRepository, key: ConsolidationUnitKey
    ) -> ConsolidationClaim | None:
        claim = await original_claim(self, key)
        if claim is not None:
            if deadline_seconds is not None:
                claim = dataclasses.replace(
                    claim,
                    deadline_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(seconds=deadline_seconds),
                )
            claims.append(claim)
        return claim

    monkeypatch.setattr(ConsolidationOwnershipRepository, "claim", capture_claim)
    block = _BlockedResolution(block_at)
    monkeypatch.setattr(jobs, "resolve_model_candidate_runtime", block.resolve)
    clients: list[_Client] = []

    def client_factory(**kwargs: object) -> _Client:
        client = _Client()
        clients.append(client)
        return client

    def unused_provider(
        *, provider: LLMProvider, credential_kwargs: dict[str, object]
    ) -> ProviderModelFactory:
        raise AssertionError("Only the native synthetic client is expected.")

    hosts: list[ConsolidationIterationHost] = []

    async def quota_host(self: ConsolidationIterationHost) -> object:
        hosts.append(self)
        selection = self.model.selection
        await self.close()
        raise ModelProviderFailure(
            operation="historical_memory",
            category=ModelProviderFailureCategory.QUOTA_OR_BILLING,
            retryability=ModelProviderFailureRetryability.USER_ACTION_REQUIRED,
            provider_message=None,
            status_code=429,
            provider_code="insufficient_quota",
            provider_error_type=None,
            provider_error_param=None,
            retry_hint_seconds=None,
            provider=selection.provider.value,
            integration=selection.llm_provider_integration_id,
            model=selection.model_identifier,
        )

    monkeypatch.setattr(ConsolidationIterationHost, "run", quota_host)
    clock = _Clock()
    watchdog = make_test_model_stream_watchdog()
    watchdog.clock = clock
    config = Mock(spec=Config)
    config.openai_responses_websocket_enabled = False
    service = jobs.HistoricalMemoryConsolidationService(
        manager,
        config,
        AgentRepository(),
        ModelCandidateHealthRepository(manager),
        _active_metadata_repository(structured_output=True),
        EngineModelReadRepository(manager, Mock(spec=LLMProviderIntegrationRepository)),
        ModelMetadataService(
            ModelMetadataReadRepository(manager, ModelMetadataSourceRepository())
        ),
        Mock(spec=EngineRuntimeTokenResolver),
        ModelSDKFactories(client_factory, unused_provider),
        watchdog,
    )
    return _Harness(service, corpus.team, block, clock, claims, clients, hosts)


async def _assert_no_dispatch_or_publication(
    manager: SessionManager[WriteSession],
    harness: _Harness,
) -> None:
    claim = harness.claims[0]
    async with manager() as session:
        attempt = await session.read_session.get(
            RDBConsolidationAttempt, claim.principal.attempt_id
        )
        assert attempt is not None and attempt.model_requests == 0
        assert attempt.completed_revision_id is None
    assert all(client.closed for client in harness.clients)
    assert len(harness.hosts) == harness.block.block_at - 1
    assert all(host.closed and host.messages == [] for host in harness.hosts)
    assert (
        await ConsolidationPublicationRepository(manager).inspect_outcome(
            claim.principal
        )
        is None
    )


@pytest.mark.parametrize("block_at", [1, 2])
async def test_claim_heartbeat_remains_active_during_setup_and_quota_handoff(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    block_at: int,
) -> None:
    harness = await _harness(
        rdb_session_manager, monkeypatch, block_at=block_at, deadline_seconds=None
    )
    task = asyncio.create_task(harness.service.run_unit(harness.key))
    try:
        async with asyncio.timeout(5):
            await harness.block.started.wait()
            assert await harness.clock.requests.get() == 30
            claim = harness.claims[0]
            before = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                seconds=60
            )
            async with rdb_session_manager() as session:
                unit = await session.read_session.get(
                    RDBConsolidationUnit, claim.unit_id
                )
                assert unit is not None
                unit.lease_until = before
            await harness.clock.ticks.put(None)
            assert await harness.clock.requests.get() == 30
            async with rdb_session_manager() as session:
                unit = await session.read_session.get(
                    RDBConsolidationUnit, claim.unit_id
                )
                assert (
                    unit is not None
                    and unit.lease_until is not None
                    and unit.lease_until > before
                )
            assert not task.done()
    finally:
        task.cancel("worker-shutdown")
        with pytest.raises(asyncio.CancelledError, match="worker-shutdown"):
            await task
    assert harness.block.stopped.is_set()
    await _assert_no_dispatch_or_publication(rdb_session_manager, harness)


@pytest.mark.parametrize("block_at", [1, 2])
async def test_renewal_authority_loss_quiesces_setup_or_handoff_without_late_work(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    block_at: int,
) -> None:
    harness = await _harness(
        rdb_session_manager, monkeypatch, block_at=block_at, deadline_seconds=None
    )
    task = asyncio.create_task(harness.service.run_unit(harness.key))
    async with asyncio.timeout(5):
        await harness.block.started.wait()
        assert await harness.clock.requests.get() == 30
        async with rdb_session_manager() as session:
            unit = await session.read_session.get(
                RDBConsolidationUnit, harness.claims[0].unit_id
            )
            assert unit is not None
            unit.owner_token = "b" * 32
        await harness.clock.ticks.put(None)
        with pytest.raises(ConsolidationAuthorityError):
            await task
    assert harness.block.stopped.is_set()
    await _assert_no_dispatch_or_publication(rdb_session_manager, harness)


@pytest.mark.parametrize("block_at", [1, 2])
async def test_absolute_claim_deadline_cancels_blocked_setup_or_handoff(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    block_at: int,
) -> None:
    # Wall-clock passage here is the elapsed-time contract under test. Ordering
    # still uses the resolution-start event, never a sleep or scheduler yield.
    harness = await _harness(
        rdb_session_manager, monkeypatch, block_at=block_at, deadline_seconds=1.0
    )
    task = asyncio.create_task(harness.service.run_unit(harness.key))
    async with asyncio.timeout(5):
        await harness.block.started.wait()
        with pytest.raises(TimeoutError):
            await task
    assert harness.block.stopped.is_set()
    await _assert_no_dispatch_or_publication(rdb_session_manager, harness)


def _active_metadata_repository(*, structured_output: bool) -> AsyncMock:
    """Capture synthetic exact declarations, never the saved capability object."""
    repository = AsyncMock(spec=ActiveModelCapabilitiesRepository)

    async def capture(
        session: WriteSession,
        *,
        workspace_id: str,
        identities: tuple[ConfiguredModelIdentity, ...],
    ) -> CapturedActiveChoiceInputs:
        del session
        choices = []
        for identity in identities:
            key = catalog_source_keys(
                provider=identity.provider, model_identifier=identity.model_identifier
            )[0]
            source = decode_catalog_source(
                json.dumps(
                    {
                        key.source_model_key: {
                            "litellm_provider": key.provider,
                            "mode": "chat",
                            "supported_endpoints": ["/v1/responses"],
                            "supported_modalities": ["text"],
                            "supported_output_modalities": ["text"],
                            "supports_function_calling": True,
                            "supports_response_schema": structured_output,
                            "max_input_tokens": 128000,
                            "max_output_tokens": 16384,
                        }
                    }
                ).encode()
            ).models[0]
            choices.append(
                CapturedStoredChoice(
                    identity=identity,
                    source_metadata=None,
                    source_models=(source,),
                    supported_execution_options=(),
                    model_developer=None,
                    catalog_id="synthetic-local-catalog",
                )
            )
        return CapturedActiveChoiceInputs(
            workspace_id=workspace_id,
            choices=tuple(choices),
            catalog_choices=(),
            source_metadata=None,
            source_expectations=(),
        )

    repository.capture_exact_choices_in_session.side_effect = capture
    repository.inputs_match_in_session.return_value = True
    return repository
