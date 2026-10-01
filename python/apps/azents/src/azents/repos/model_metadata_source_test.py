"""Model metadata source repository tests."""

import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.model_metadata_source import ModelMetadataSourcePayload
from azents.repos.model_metadata_source import ModelMetadataSourceRepository

pytestmark = pytest.mark.asyncio

_SOURCE_KEY = "genai_prices"


async def test_publish_selects_current_content_addressed_snapshot(
    rdb_session: AsyncSession,
) -> None:
    """Successful publication selects one durable current source snapshot."""
    repository = ModelMetadataSourceRepository()
    started_at = datetime.datetime.now(datetime.UTC)
    attempt_id = await repository.begin_attempt(
        rdb_session,
        source_key=_SOURCE_KEY,
        started_at=started_at,
    )
    authority = await repository.lock_authority(
        rdb_session,
        source_key=_SOURCE_KEY,
    )
    payload = ModelMetadataSourcePayload(providers=[])

    published = await repository.publish_snapshot(
        rdb_session,
        authority=authority,
        attempt_id=attempt_id,
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=0,
        model_count=0,
        payload=payload,
        finished_at=datetime.datetime.now(datetime.UTC),
        diagnostics={"source_kind": "genai_prices"},
    )

    assert published is not None
    current = await repository.get_current(rdb_session, source_key=_SOURCE_KEY)
    attempt = await repository.get_latest_attempt(
        rdb_session,
        source_key=_SOURCE_KEY,
    )
    assert current == published
    assert current.payload.providers == []
    assert attempt is not None
    assert attempt.produced_snapshot_id == current.id
    assert attempt.status.value == "succeeded"


async def test_newer_attempt_supersedes_older_publication(
    rdb_session: AsyncSession,
) -> None:
    """An older completion cannot replace the latest source authority."""
    repository = ModelMetadataSourceRepository()
    first = await repository.begin_attempt(
        rdb_session,
        source_key=_SOURCE_KEY,
        started_at=datetime.datetime.now(datetime.UTC),
    )
    second = await repository.begin_attempt(
        rdb_session,
        source_key=_SOURCE_KEY,
        started_at=datetime.datetime.now(datetime.UTC),
    )
    authority = await repository.lock_authority(
        rdb_session,
        source_key=_SOURCE_KEY,
    )
    payload = ModelMetadataSourcePayload(providers=[])

    published = await repository.publish_snapshot(
        rdb_session,
        authority=authority,
        attempt_id=first,
        source_kind="genai_prices",
        source_schema_version="1",
        source_url="https://metadata.example/data.json",
        source_hash=payload.content_hash(),
        producer_name="genai-prices",
        producer_version="0.1.9",
        provider_count=0,
        model_count=0,
        payload=payload,
        finished_at=datetime.datetime.now(datetime.UTC),
        diagnostics={"source_kind": "genai_prices"},
    )

    assert first != second
    assert published is None
    assert await repository.get_current(rdb_session, source_key=_SOURCE_KEY) is None
