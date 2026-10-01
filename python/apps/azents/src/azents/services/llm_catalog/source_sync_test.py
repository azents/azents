"""LiteLLM source sync tests."""

import asyncio
import datetime
import hashlib
import json
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMCatalogAttemptStatus
from azents.rdb.models.llm_catalog import RDBLLMCatalogSyncAttempt
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LiteLLMSourceSnapshotRepository
from azents.services.llm_catalog import (
    LiteLLMSourceLoader,
    LiteLLMSourceSyncError,
    LiteLLMSourceSyncService,
)

_SOURCE_URL = "https://catalog.example.test/models.json"


def _payload(count: int, *, generation: int = 1) -> dict[str, dict[str, Any]]:
    return {
        f"openai/model-{generation}-{index}": {
            "litellm_provider": "openai",
            "mode": "chat",
        }
        for index in range(count)
    }


def _source_hash(payload: dict[str, dict[str, Any]]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _service(
    session_manager: SessionManager[AsyncSession],
    handler: (
        Callable[[httpx.Request], httpx.Response]
        | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
    ),
) -> tuple[LiteLLMSourceSyncService, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    repository = LiteLLMSourceSnapshotRepository()
    return (
        LiteLLMSourceSyncService(
            session_manager=session_manager,
            snapshot_repository=repository,
            source_loader=LiteLLMSourceLoader(
                http_client=client,
                source_url=_SOURCE_URL,
            ),
        ),
        client,
    )


async def test_successful_remote_ingestion_publishes_authoritative_snapshot(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Persist validated remote content and source change diagnostics."""
    payload = _payload(100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    service, client = _service(rdb_session_manager, handler)
    async with client:
        snapshot = await service.sync_current_source()

    assert snapshot.loaded_source == "remote"
    assert snapshot.source_url == _SOURCE_URL
    assert snapshot.model_count == 100
    assert snapshot.source_hash == _source_hash(payload)
    assert snapshot.litellm_version is None

    async with rdb_session_manager() as session:
        attempt = await LiteLLMSourceSnapshotRepository().get_latest_attempt(
            session,
            source_key="litellm_model_cost",
        )

    assert attempt is not None
    assert attempt.status == LLMCatalogAttemptStatus.SUCCEEDED
    assert attempt.produced_snapshot_id == snapshot.id
    assert attempt.diagnostics is not None
    assert attempt.diagnostics["source_kind"] == "remote"
    assert len(attempt.diagnostics["added_models"]) == 100
    assert attempt.diagnostics["removed_models"] == []


async def test_remote_ingestion_promotes_matching_runtime_snapshot(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Promote content previously stored without authoritative provenance."""
    payload = _payload(100)
    repository = LiteLLMSourceSnapshotRepository()
    async with rdb_session_manager() as session:
        legacy = await repository.create_if_missing(
            session,
            source_key="litellm_model_cost",
            source_url=_SOURCE_URL,
            source_hash=_source_hash(payload),
            model_count=len(payload),
            litellm_version="1.91.3",
            loaded_source="litellm_runtime",
            payload=payload,
        )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    service, client = _service(rdb_session_manager, handler)
    async with client:
        snapshot = await service.sync_current_source()

    assert snapshot.id == legacy.id
    assert snapshot.loaded_source == "remote"
    assert snapshot.litellm_version == legacy.litellm_version == "1.91.3"
    assert snapshot.payload == legacy.payload


async def test_new_source_attempt_recovers_unfinished_attempt(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Mark an abandoned source attempt failed when the next sync begins."""
    repository = LiteLLMSourceSnapshotRepository()
    async with rdb_session_manager() as session:
        abandoned_attempt_id = await repository.begin_attempt(
            session,
            source_key="litellm_model_cost",
            started_at=datetime.datetime(2026, 8, 18, tzinfo=datetime.UTC),
        )

    payload = _payload(100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    service, client = _service(rdb_session_manager, handler)
    async with client:
        await service.sync_current_source()

    async with rdb_session_manager() as session:
        abandoned = await session.get(
            RDBLLMCatalogSyncAttempt,
            abandoned_attempt_id,
        )

    assert abandoned is not None
    assert abandoned.status == LLMCatalogAttemptStatus.FAILED
    assert abandoned.failure_code == "LiteLLMSourceSyncInterrupted"
    assert abandoned.finished_at is not None


async def test_same_hash_refresh_preserves_historical_package_provenance(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Refresh validated authority without erasing a historical version."""
    payload = _payload(100)
    repository = LiteLLMSourceSnapshotRepository()
    async with rdb_session_manager() as session:
        previous = await repository.upsert_validated_remote(
            session,
            source_key="litellm_model_cost",
            source_url=_SOURCE_URL,
            source_hash=_source_hash(payload),
            model_count=len(payload),
            litellm_version="historical-package-version",
            payload=payload,
        )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    service, client = _service(rdb_session_manager, handler)
    async with client:
        refreshed = await service.sync_current_source()
        authoritative = await service.get_authoritative_source()

    assert refreshed.id == previous.id == authoritative.id
    assert refreshed.source_hash == previous.source_hash
    assert refreshed.payload == previous.payload
    assert refreshed.litellm_version == "historical-package-version"
    async with rdb_session_manager() as session:
        attempt = await repository.get_latest_attempt(
            session,
            source_key="litellm_model_cost",
        )
    assert attempt is not None
    assert attempt.status == LLMCatalogAttemptStatus.SUCCEEDED
    assert attempt.produced_snapshot_id == previous.id


async def test_remote_ingestion_retains_unconsumed_source_metadata(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Snapshot collection does not strip prices or provider source extensions."""
    payload = {
        "openai/canonical": {
            "litellm_provider": "openai",
            "mode": "chat",
            "aliases": ["openai/alias"],
            "input_cost_per_token_priority": 0.000004,
            "source_extension": {"nested": ["untouched", 5]},
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    service, client = _service(rdb_session_manager, handler)
    async with client:
        snapshot = await service.sync_current_source()
    for model_key in ("openai/canonical", "openai/alias"):
        metadata = snapshot.payload[model_key]
        assert metadata["input_cost_per_token_priority"] == 0.000004
        assert metadata["source_extension"] == {"nested": ["untouched", 5]}


async def test_remote_ingestion_expands_litellm_aliases(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Preserve LiteLLM alias expansion at the explicit ingestion boundary."""
    payload = {
        "openai/canonical": {
            "litellm_provider": "openai",
            "mode": "chat",
            "aliases": ["openai/alias"],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    service, client = _service(rdb_session_manager, handler)
    async with client:
        snapshot = await service.sync_current_source()

    assert set(snapshot.payload) == {"openai/canonical", "openai/alias"}
    assert "aliases" not in snapshot.payload["openai/canonical"]
    assert snapshot.payload["openai/alias"] == snapshot.payload["openai/canonical"]


async def test_remote_failure_keeps_authority_without_package_fallback(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Keep validated remote authority and record only the failed fetch."""
    payload = _payload(100)

    def success_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    success_service, success_client = _service(rdb_session_manager, success_handler)
    async with success_client:
        original = await success_service.sync_current_source()

    def failure_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("remote unavailable", request=request)

    failure_service, failure_client = _service(rdb_session_manager, failure_handler)
    async with failure_client:
        with pytest.raises(LiteLLMSourceSyncError):
            await failure_service.sync_current_source()
        authoritative = await failure_service.get_authoritative_source()

    assert authoritative.id == original.id
    assert authoritative.source_hash == original.source_hash

    async with rdb_session_manager() as session:
        attempt = await LiteLLMSourceSnapshotRepository().get_latest_attempt(
            session,
            source_key="litellm_model_cost",
        )

    assert attempt is not None
    assert attempt.status == LLMCatalogAttemptStatus.FAILED
    assert attempt.diagnostics is not None
    assert attempt.diagnostics["source_kind"] == "remote"
    assert attempt.diagnostics["litellm_version"] is None
    assert not any(key.startswith("fallback_") for key in attempt.diagnostics)
    assert attempt.failure_code == "ConnectError"
    assert attempt.diagnostics["fetch_failure_reason"] == (
        "The remote LiteLLM model catalog could not be ingested."
    )


async def test_malformed_remote_payload_keeps_authoritative_snapshot(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Reject malformed remote JSON without publishing the package fallback."""
    payload = _payload(100)

    def success_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    success_service, success_client = _service(rdb_session_manager, success_handler)
    async with success_client:
        original = await success_service.sync_current_source()

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"invalid": "not-an-object"}, request=request)

    malformed_service, malformed_client = _service(
        rdb_session_manager, malformed_handler
    )
    async with malformed_client:
        with pytest.raises(LiteLLMSourceSyncError):
            await malformed_service.sync_current_source()
        authoritative = await malformed_service.get_authoritative_source()

    assert authoritative.id == original.id

    async with rdb_session_manager() as session:
        attempt = await LiteLLMSourceSnapshotRepository().get_latest_attempt(
            session,
            source_key="litellm_model_cost",
        )

    assert attempt is not None
    assert attempt.status == LLMCatalogAttemptStatus.FAILED
    assert attempt.diagnostics is not None
    assert attempt.diagnostics["source_kind"] == "remote"
    assert not any(key.startswith("fallback_") for key in attempt.diagnostics)


async def test_invalid_utf8_remote_payload_records_failed_attempt(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Terminalize source attempts when the remote JSON cannot be decoded."""

    def invalid_utf8_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\xff",
            headers={"content-type": "application/json"},
            request=request,
        )

    service, client = _service(rdb_session_manager, invalid_utf8_handler)
    async with client:
        with pytest.raises(LiteLLMSourceSyncError):
            await service.sync_current_source()

    async with rdb_session_manager() as session:
        attempt = await LiteLLMSourceSnapshotRepository().get_latest_attempt(
            session,
            source_key="litellm_model_cost",
        )

    assert attempt is not None
    assert attempt.status == LLMCatalogAttemptStatus.FAILED
    assert attempt.finished_at is not None


async def test_remote_failure_does_not_persist_untrusted_exception_text(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Provider or parser text cannot become a durable source diagnostic."""
    canary = "untrusted-source-body-and-credential-canary"

    def failure_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(canary, request=request)

    service, client = _service(rdb_session_manager, failure_handler)
    async with client:
        with pytest.raises(LiteLLMSourceSyncError) as raised:
            await service.sync_current_source()
        assert canary not in str(raised.value)
        assert raised.value.__cause__ is None
        assert raised.value.__suppress_context__

    async with rdb_session_manager() as session:
        attempt = await LiteLLMSourceSnapshotRepository().get_latest_attempt(
            session,
            source_key="litellm_model_cost",
        )

    assert attempt is not None
    assert attempt.status == LLMCatalogAttemptStatus.FAILED
    assert attempt.finished_at is not None
    assert attempt.diagnostics is not None
    assert canary not in json.dumps(attempt.diagnostics)
    assert canary not in (attempt.failure_message or "")
    assert attempt.failure_code == "ConnectError"


async def test_materially_smaller_remote_payload_is_blocked(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Quarantine an unexplained model-count reduction before publication."""
    original_payload = _payload(100)

    def original_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=original_payload, request=request)

    original_service, original_client = _service(rdb_session_manager, original_handler)
    async with original_client:
        original = await original_service.sync_current_source()

    reduced_payload = _payload(40)

    def reduced_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reduced_payload, request=request)

    reduced_service, reduced_client = _service(rdb_session_manager, reduced_handler)
    async with reduced_client:
        with pytest.raises(
            LiteLLMSourceSyncError,
            match="materially smaller",
        ):
            await reduced_service.sync_current_source()
        authoritative = await reduced_service.get_authoritative_source()

    assert authoritative.id == original.id

    async with rdb_session_manager() as session:
        attempt = await LiteLLMSourceSnapshotRepository().get_latest_attempt(
            session,
            source_key="litellm_model_cost",
        )

    assert attempt is not None
    assert attempt.failure_code == "LiteLLMSourceModelCountReduction"
    assert attempt.diagnostics is not None
    assert len(attempt.diagnostics["removed_models"]) == 60
    assert attempt.diagnostics["provider_count_changes"] == {
        "openai": {"previous": 100, "current": 40, "delta": -60}
    }


async def test_source_recovers_after_remote_failure(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Publish a later valid source after a failed remote attempt."""
    requests = 0
    recovered_payload = _payload(101, generation=2)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            raise httpx.ConnectError("temporary outage", request=request)
        return httpx.Response(200, json=recovered_payload, request=request)

    service, client = _service(rdb_session_manager, handler)
    async with client:
        with pytest.raises(LiteLLMSourceSyncError):
            await service.sync_current_source()
        snapshot = await service.sync_current_source()

    assert snapshot.loaded_source == "remote"
    assert snapshot.model_count == 101
    assert snapshot.payload == recovered_payload


async def test_authoritative_read_does_not_fetch_remote_source(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Read the DB authority without adding a remote dependency."""
    payload = _payload(100)

    def success_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    service, client = _service(rdb_session_manager, success_handler)
    async with client:
        original = await service.sync_current_source()

    def unexpected_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected remote request: {request.url}")

    read_service, read_client = _service(rdb_session_manager, unexpected_handler)
    async with read_client:
        authoritative = await read_service.get_authoritative_source()

    assert authoritative.id == original.id


async def test_older_concurrent_attempt_cannot_replace_newer_authority(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Fence an older remote result that completes after a newer attempt."""
    older_payload = _payload(100, generation=1)
    newer_payload = _payload(100, generation=2)
    older_fetch_started = asyncio.Event()
    release_older_fetch = asyncio.Event()

    async def older_handler(request: httpx.Request) -> httpx.Response:
        older_fetch_started.set()
        await release_older_fetch.wait()
        return httpx.Response(200, json=older_payload, request=request)

    def newer_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=newer_payload, request=request)

    older_service, older_client = _service(rdb_session_manager, older_handler)
    newer_service, newer_client = _service(rdb_session_manager, newer_handler)
    async with older_client, newer_client:
        older_task = asyncio.create_task(older_service.sync_current_source())
        await older_fetch_started.wait()
        newer = await newer_service.sync_current_source()
        release_older_fetch.set()
        with pytest.raises(LiteLLMSourceSyncError, match="superseded"):
            await older_task
        authoritative = await newer_service.get_authoritative_source()

    assert authoritative.id == newer.id
    assert authoritative.payload == newer_payload
