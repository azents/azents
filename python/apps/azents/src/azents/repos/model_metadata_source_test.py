"""Current source persistence, lossless prices and exact narrow reads."""

import datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa

from azents.core.enums import LLMProvider
from azents.core.model_catalog_identity import CatalogIdentityError
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CatalogSourcePayload,
    decode_catalog_source,
)
from azents.core.model_metadata_collection_data import (
    CurrentSourceModel,
    FetchedModelMetadataSource,
)
from azents.core.model_pricing import normalize_model_pricing
from azents.rdb.models.model_metadata_source import RDBModelMetadataSourceModel
from azents.rdb.session_capabilities import WriteSession
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import (
    ContextModelRequest,
    SourceModelExpectation,
    SourceProjectionMetadata,
)
from azents.testing.model_metadata import make_test_source_payload

_NOW = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)
pytestmark = pytest.mark.asyncio


def _fetched(
    payload: CatalogSourcePayload, *, collected_at: datetime.datetime = _NOW
) -> FetchedModelMetadataSource:
    return FetchedModelMetadataSource(
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=payload.schema_version,
        source_url="https://metadata.example.test/current.json",
        producer_name="LiteLLM public catalog",
        producer_version=None,
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        models=tuple(
            CurrentSourceModel(
                model=model,
                pricing=normalize_model_pricing(
                    source_key=CATALOG_SOURCE_KEY,
                    source_model=model,
                    collected_at=collected_at,
                ),
                collected_at=collected_at,
            )
            for model in payload.models
        ),
        collected_at=collected_at,
    )


async def _publish(
    session: WriteSession,
    repository: ModelMetadataSourceRepository,
    fetched: FetchedModelMetadataSource,
) -> None:
    token = await repository.begin_sync(
        session, source_key=CATALOG_SOURCE_KEY, started_at=fetched.collected_at
    )
    owner = await repository.lock_authority(session, source_key=CATALOG_SOURCE_KEY)
    assert owner is not None
    await repository.replace_current(
        session,
        owner=owner,
        work_token=token,
        fetched=fetched,
        finished_at=fetched.collected_at,
        diagnostics={},
    )


async def test_overwrite_retains_only_current_keys_and_updates_price(
    rdb_session: WriteSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    first = _fetched(
        make_test_source_payload(
            {
                "literal": {
                    "litellm_provider": "openai",
                    "input_cost_per_token": 0.000001,
                    "output_cost_per_token": 0.000002,
                },
                "removed": {"litellm_provider": "openai"},
            }
        )
    )
    await _publish(rdb_session, repository, first)
    second = _fetched(
        make_test_source_payload(
            {
                "literal": {
                    "litellm_provider": "openai",
                    "input_cost_per_token": 0.000003,
                    "output_cost_per_token": 0.000004,
                }
            }
        ),
        collected_at=_NOW + datetime.timedelta(seconds=1),
    )
    await _publish(rdb_session, repository, second)
    current = await repository.get_current(rdb_session, source_key=CATALOG_SOURCE_KEY)
    assert current is not None
    assert current.models == second.models
    assert current.payload == second.payload
    count = await rdb_session.read_session.scalar(
        sa.select(sa.func.count()).select_from(RDBModelMetadataSourceModel)
    )
    assert count == 1
    status = await repository.get_sync_status(
        rdb_session, source_key=CATALOG_SOURCE_KEY
    )
    assert status is not None
    assert status.work_token is None
    assert status.status.value == "succeeded"


async def test_lossless_decimal_survives_jsonb_and_current_restore(
    rdb_session: WriteSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    payload = decode_catalog_source(
        b'{"literal":{"litellm_provider":"openai","input_cost_per_token":0.000000000000000000123456789,"output_cost_per_token":0.000002}}'
    )
    fetched = _fetched(payload)
    await _publish(rdb_session, repository, fetched)
    current = await repository.get_current(rdb_session, source_key=CATALOG_SOURCE_KEY)
    assert current is not None
    assert current.models[0].pricing == fetched.models[0].pricing
    rules = current.models[0].pricing.rules
    assert rules is not None
    assert rules.rates[0].usd_per_unit == Decimal("0.000000000000000000123456789")


async def test_late_failure_cannot_replace_newer_work_status(
    rdb_session: WriteSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    first = await repository.begin_sync(
        rdb_session, source_key=CATALOG_SOURCE_KEY, started_at=_NOW
    )
    second = await repository.begin_sync(
        rdb_session,
        source_key=CATALOG_SOURCE_KEY,
        started_at=_NOW + datetime.timedelta(seconds=1),
    )
    changed = await repository.fail_sync(
        rdb_session,
        source_key=CATALOG_SOURCE_KEY,
        work_token=first,
        finished_at=_NOW,
        failure_code="LateFailure",
        failure_message="Late source failure.",
        action_hint=None,
        diagnostics={},
    )
    assert not changed
    status = await repository.get_sync_status(
        rdb_session, source_key=CATALOG_SOURCE_KEY
    )
    assert status is not None
    assert status.work_token == second
    assert status.status.value == "running"


async def test_failure_preserves_last_success_and_current_models(
    rdb_session: WriteSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    fetched = _fetched(
        make_test_source_payload({"literal": {"litellm_provider": "openai"}})
    )
    await _publish(rdb_session, repository, fetched)
    token = await repository.begin_sync(
        rdb_session,
        source_key=CATALOG_SOURCE_KEY,
        started_at=_NOW + datetime.timedelta(hours=1),
    )
    assert await repository.fail_sync(
        rdb_session,
        source_key=CATALOG_SOURCE_KEY,
        work_token=token,
        finished_at=_NOW + datetime.timedelta(hours=1),
        failure_code="FetchFailed",
        failure_message="Collection failed.",
        action_hint=None,
        diagnostics={},
    )
    current = await repository.get_current(rdb_session, source_key=CATALOG_SOURCE_KEY)
    assert current is not None
    assert current.models == fetched.models
    assert current.collected_at == _NOW


async def test_context_query_is_exact_scoped_and_requested_only(
    rdb_session: WriteSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    fetched = _fetched(
        make_test_source_payload(
            {
                "literal": {"litellm_provider": "openai", "max_input_tokens": 4096},
                "chatgpt/literal": {
                    "litellm_provider": "chatgpt",
                    "max_input_tokens": 8192,
                },
                "unrequested": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 32768,
                },
            }
        )
    )
    await _publish(rdb_session, repository, fetched)
    capture = await repository.capture_for_context(
        rdb_session,
        requests=[
            ContextModelRequest(
                provider=LLMProvider.OPENAI, model_identifier="literal"
            ),
            ContextModelRequest(
                provider=LLMProvider.CHATGPT_OAUTH, model_identifier="literal"
            ),
            ContextModelRequest(
                provider=LLMProvider.OPENAI, model_identifier="openai/literal"
            ),
        ],
    )
    assert [row.max_input_tokens for row in capture.models] == [4096, 8192, None]
    assert len(capture.models) == 3


async def test_ambiguous_exact_vertex_namespaces_do_not_choose_one(
    rdb_session: WriteSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    fetched = _fetched(
        make_test_source_payload(
            {
                "vertex_ai/literal": {
                    "litellm_provider": "vertex_ai-language-models",
                    "max_input_tokens": 8192,
                }
            }
        )
    )
    # A dictionary cannot express the same exact producer key twice; add another
    # hosting namespace through validated typed records instead.
    model = fetched.payload.models[0]
    twin = model.model_copy(update={"provider": "vertex_ai"})
    payload = fetched.payload.model_copy(
        update={
            "models": tuple(
                sorted((model, twin), key=lambda item: (item.provider, item.source_key))
            )
        }
    )
    await _publish(rdb_session, repository, _fetched(payload))
    with pytest.raises(CatalogIdentityError):
        await repository.capture_for_context(
            rdb_session,
            requests=[
                ContextModelRequest(
                    provider=LLMProvider.GOOGLE_VERTEX_AI, model_identifier="literal"
                )
            ],
        )


async def test_value_and_absence_checks_do_not_use_work_token(
    rdb_session: WriteSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    fetched = _fetched(
        make_test_source_payload(
            {"literal": {"litellm_provider": "openai", "max_input_tokens": 4096}}
        )
    )
    await _publish(rdb_session, repository, fetched)
    metadata = SourceProjectionMetadata(
        source_key=CATALOG_SOURCE_KEY,
        source_kind=fetched.source_kind,
        collected_at=fetched.collected_at,
    )
    expectations = (
        SourceModelExpectation(
            provider="openai", source_model_key="literal", current=fetched.models[0]
        ),
        SourceModelExpectation(
            provider="openai", source_model_key="added", current=None
        ),
    )
    assert await repository.projection_inputs_match(
        rdb_session, expected_metadata=metadata, expectations=expectations
    )
    changed = _fetched(
        make_test_source_payload(
            {"literal": {"litellm_provider": "openai", "max_input_tokens": 8192}}
        )
    )
    await _publish(rdb_session, repository, changed)
    assert not await repository.projection_inputs_match(
        rdb_session, expected_metadata=metadata, expectations=expectations
    )
    assert changed.collected_at == fetched.collected_at
    assert changed.models[0] != fetched.models[0]
    added = _fetched(
        make_test_source_payload(
            {
                "literal": {"litellm_provider": "openai", "max_input_tokens": 4096},
                "added": {"litellm_provider": "openai"},
            }
        )
    )
    await _publish(rdb_session, repository, added)
    assert not await repository.projection_inputs_match(
        rdb_session, expected_metadata=metadata, expectations=expectations
    )
