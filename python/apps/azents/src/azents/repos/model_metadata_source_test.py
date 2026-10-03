"""Durable publication and strict snapshot restoration tests."""

import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    ModelMetadataSourceKind,
)
from azents.rdb.models.model_metadata_source import RDBModelMetadataSourceSnapshot
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.testing.model_metadata import make_test_source_payload


async def test_publish_selects_current_content_addressed_snapshot(
    rdb_session: AsyncSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    attempt_id = await repository.begin_attempt(
        rdb_session,
        source_key=CATALOG_SOURCE_KEY,
        started_at=datetime.datetime.now(datetime.UTC),
    )
    authority = await repository.lock_authority(
        rdb_session, source_key=CATALOG_SOURCE_KEY
    )
    payload = make_test_source_payload({"literal": {"litellm_provider": "openai"}})
    published = await repository.publish_snapshot(
        rdb_session,
        authority=authority,
        attempt_id=attempt_id,
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=payload.schema_version,
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash,
        producer_name="LiteLLM public catalog",
        producer_version="fixture-data-1",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        finished_at=datetime.datetime.now(datetime.UTC),
        diagnostics={"source_kind": CATALOG_SOURCE_KIND},
    )
    assert published is not None
    current = await repository.get_current(rdb_session, source_key=CATALOG_SOURCE_KEY)
    attempt = await repository.get_latest_attempt(
        rdb_session, source_key=CATALOG_SOURCE_KEY
    )
    assert current == published
    assert current.payload == payload
    assert attempt is not None
    assert attempt.produced_snapshot_id == current.id
    assert attempt.status.value == "succeeded"


async def test_newer_attempt_supersedes_older_publication(
    rdb_session: AsyncSession,
) -> None:
    repository = ModelMetadataSourceRepository()
    first = await repository.begin_attempt(
        rdb_session,
        source_key=CATALOG_SOURCE_KEY,
        started_at=datetime.datetime.now(datetime.UTC),
    )
    second = await repository.begin_attempt(
        rdb_session,
        source_key=CATALOG_SOURCE_KEY,
        started_at=datetime.datetime.now(datetime.UTC),
    )
    authority = await repository.lock_authority(
        rdb_session, source_key=CATALOG_SOURCE_KEY
    )
    payload = make_test_source_payload({"literal": {"litellm_provider": "openai"}})
    published = await repository.publish_snapshot(
        rdb_session,
        authority=authority,
        attempt_id=first,
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=payload.schema_version,
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash,
        producer_name="LiteLLM public catalog",
        producer_version="fixture-data-1",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        finished_at=datetime.datetime.now(datetime.UTC),
        diagnostics={"source_kind": CATALOG_SOURCE_KIND},
    )
    assert first != second
    assert published is None
    assert (
        await repository.get_current(rdb_session, source_key=CATALOG_SOURCE_KEY) is None
    )


def _row() -> RDBModelMetadataSourceSnapshot:
    payload = make_test_source_payload(
        {"literal": {"litellm_provider": "openai", "max_input_tokens": 128_000}}
    )
    row = RDBModelMetadataSourceSnapshot(
        id="s" * 32,
        source_key=CATALOG_SOURCE_KEY,
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=payload.schema_version,
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash,
        producer_name="LiteLLM public catalog",
        producer_version="fixture-data-1",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload.model_dump(mode="json"),
    )
    row.created_at = datetime.datetime.now(datetime.UTC)
    return row


def test_repository_restores_json_strict_contract() -> None:
    snapshot = ModelMetadataSourceRepository._build_snapshot(_row())
    assert snapshot.payload.models[0].facts.max_input_tokens.value == 128_000


@pytest.mark.parametrize(
    "mutation",
    ["old_family", "wrong_hash", "wrong_counts", "coerced_number", "unknown_field"],
)
def test_repository_rejects_inconsistent_or_permissive_snapshot(mutation: str) -> None:
    row = _row()
    match mutation:
        case "old_family":
            row.source_key = "genai_prices"
            row.source_kind = ModelMetadataSourceKind.GENAI_PRICES
        case "wrong_hash":
            row.source_hash = "0" * 64
        case "wrong_counts":
            row.model_count = 2
        case "coerced_number":
            row.payload = {**row.payload, "model_count": "1"}
        case "unknown_field":
            row.payload = {**row.payload, "unexpected": True}
    with pytest.raises(ValueError):
        ModelMetadataSourceRepository._build_snapshot(row)
