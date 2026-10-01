"""Azents-owned collection of the Pydantic ecosystem model metadata source."""

from __future__ import annotations

import dataclasses
import datetime
import importlib.metadata
import ipaddress
import json
import os
from typing import Annotated
from urllib.parse import urlsplit

import anyio.to_thread
import httpx2
from fastapi import Depends
from genai_prices import UpdatePrices
from genai_prices.data_snapshot import DataSnapshot
from genai_prices.update_prices import DEFAULT_UPDATE_URL
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.model_metadata_source import (
    MODEL_METADATA_SOURCE_SCHEMA_VERSION,
    ModelMetadataSourcePayload,
    encode_data_snapshot,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot

GENAI_PRICES_SOURCE_KEY = "genai_prices"
_GENAI_PRICES_REQUEST_TIMEOUT = httpx2.Timeout(timeout=20, connect=5)
_SOURCE_MIN_REMOVAL_COUNT = 50
_SOURCE_MIN_REMOVAL_RATIO = 0.02
_PROVIDER_MIN_REMOVAL_COUNT = 5
_PROVIDER_MIN_REMOVAL_RATIO = 0.20
_SUPPORTED_PROVIDER_IDS = frozenset(
    {"anthropic", "aws", "google", "moonshotai", "openai", "openrouter", "x-ai"}
)


def get_genai_prices_source_url() -> str:
    """Return the operator-configured model metadata source URL."""
    return os.environ.get("GENAI_PRICES_SOURCE_URL", DEFAULT_UPDATE_URL)


@dataclasses.dataclass(frozen=True)
class FetchedModelMetadataSource:
    """One validated remote source ready for durable publication."""

    source_kind: str
    source_schema_version: str
    source_url: str
    source_hash: str
    producer_name: str
    producer_version: str
    provider_count: int
    model_count: int
    payload: ModelMetadataSourcePayload


@dataclasses.dataclass(frozen=True)
class GenAIPricesSourceAdapter:
    """Fetch and canonicalize genai-prices data without global updater state."""

    source_url: Annotated[str, Depends(get_genai_prices_source_url)]

    async def fetch(self) -> FetchedModelMetadataSource:
        """Collect one remote snapshot through the public library boundary."""
        validate_genai_prices_source_url(self.source_url)
        snapshot = await anyio.to_thread.run_sync(self._fetch_sync)
        try:
            payload = encode_data_snapshot(snapshot)
        except AssertionError as error:
            raise ValueError(
                "The model metadata source contains an unsupported typed variant."
            ) from error
        return FetchedModelMetadataSource(
            source_kind="genai_prices",
            source_schema_version=MODEL_METADATA_SOURCE_SCHEMA_VERSION,
            source_url=self.source_url,
            source_hash=payload.content_hash(),
            producer_name="genai-prices",
            producer_version=importlib.metadata.version("genai-prices"),
            provider_count=payload.provider_count,
            model_count=payload.model_count,
            payload=payload,
        )

    def _fetch_sync(self) -> DataSnapshot:
        updater = UpdatePrices(
            url=self.source_url,
            request_timeout=_GENAI_PRICES_REQUEST_TIMEOUT,
        )
        snapshot = updater.fetch()
        if snapshot is None:
            raise ValueError("The model metadata source returned no snapshot.")
        return snapshot


def validate_genai_prices_source_url(source_url: str) -> None:
    """Allow HTTPS sources and loopback HTTP used by deterministic testenv."""
    parsed = urlsplit(source_url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("The model metadata source URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError(
            "The model metadata source URL must not contain a query or fragment."
        )
    if parsed.scheme == "https" and parsed.hostname is not None:
        return
    if parsed.scheme == "http" and parsed.hostname is not None:
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            if parsed.hostname == "localhost":
                return
        else:
            if address.is_loopback:
                return
    raise ValueError(
        "The model metadata source must use HTTPS or a loopback test endpoint."
    )


class ModelMetadataSourceSyncError(RuntimeError):
    """Model metadata source synchronization failed safely."""


@dataclasses.dataclass(frozen=True)
class ModelMetadataSourceSyncService:
    """Synchronize one validated source under Azents durable authority."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]
    source_adapter: Annotated[
        GenAIPricesSourceAdapter, Depends(GenAIPricesSourceAdapter)
    ]

    async def sync_current_source(self) -> ModelMetadataSourceSnapshot:
        """Collect, validate, and publish the current metadata source."""
        started_at = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            attempt_id = await self.repository.begin_attempt(
                session,
                source_key=GENAI_PRICES_SOURCE_KEY,
                started_at=started_at,
            )

        try:
            fetched = await self.source_adapter.fetch()
        except (
            httpx2.HTTPError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValidationError,
            ValueError,
        ) as error:
            await self._record_failure(
                attempt_id=attempt_id,
                error=error,
            )
            raise ModelMetadataSourceSyncError(
                "The remote model metadata source could not be ingested."
            ) from None

        finished_at = datetime.datetime.now(datetime.UTC)
        failure_message: str | None = None
        snapshot: ModelMetadataSourceSnapshot | None = None
        async with self.session_manager() as session:
            authority = await self.repository.lock_authority(
                session,
                source_key=GENAI_PRICES_SOURCE_KEY,
            )
            previous = await self.repository.get_current(
                session,
                source_key=GENAI_PRICES_SOURCE_KEY,
            )
            diagnostics = _source_diagnostics(previous=previous, fetched=fetched)
            if authority.latest_attempt_id != attempt_id:
                await self.repository.fail_attempt(
                    session,
                    attempt_id=attempt_id,
                    finished_at=finished_at,
                    failure_code="ModelMetadataSourceSyncSuperseded",
                    failure_message=(
                        "A newer model metadata source synchronization superseded "
                        "this result."
                    ),
                    action_hint="Use the newer source synchronization result.",
                    fetched_count=fetched.model_count,
                    diagnostics=diagnostics,
                )
                failure_message = (
                    "The model metadata source synchronization was superseded."
                )
            elif (
                reduction := _material_reduction(previous=previous, fetched=fetched)
            ) is not None:
                await self.repository.fail_attempt(
                    session,
                    attempt_id=attempt_id,
                    finished_at=finished_at,
                    failure_code="ModelMetadataSourceModelCountReduction",
                    failure_message=(
                        "The remote model metadata source is materially smaller "
                        "than the current authoritative snapshot."
                    ),
                    action_hint=(
                        "Verify the upstream removals before replacing the "
                        "authoritative source."
                    ),
                    fetched_count=fetched.model_count,
                    diagnostics={**diagnostics, "reduction_scope": reduction},
                )
                failure_message = (
                    "The model metadata source reduction requires operator review."
                )
            else:
                snapshot = await self.repository.publish_snapshot(
                    session,
                    authority=authority,
                    attempt_id=attempt_id,
                    source_kind=fetched.source_kind,
                    source_schema_version=fetched.source_schema_version,
                    source_url=fetched.source_url,
                    source_hash=fetched.source_hash,
                    producer_name=fetched.producer_name,
                    producer_version=fetched.producer_version,
                    provider_count=fetched.provider_count,
                    model_count=fetched.model_count,
                    payload=fetched.payload,
                    finished_at=finished_at,
                    diagnostics=diagnostics,
                )
        if failure_message is not None:
            raise ModelMetadataSourceSyncError(failure_message)
        if snapshot is None:
            raise ModelMetadataSourceSyncError(
                "The model metadata source synchronization was superseded."
            )
        return snapshot

    async def get_current_source(self) -> ModelMetadataSourceSnapshot | None:
        """Return the stored current source without remote work."""
        async with self.session_manager() as session:
            return await self.repository.get_current(
                session,
                source_key=GENAI_PRICES_SOURCE_KEY,
            )

    async def _record_failure(
        self,
        *,
        attempt_id: str,
        error: (
            httpx2.HTTPError
            | json.JSONDecodeError
            | UnicodeDecodeError
            | ValidationError
            | ValueError
        ),
    ) -> None:
        finished_at = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            await self.repository.fail_attempt(
                session,
                attempt_id=attempt_id,
                finished_at=finished_at,
                failure_code=type(error).__name__,
                failure_message=(
                    "The remote model metadata source could not be ingested."
                ),
                action_hint="Retry after the configured source becomes available.",
                fetched_count=0,
                diagnostics={
                    "source_kind": "genai_prices",
                    "source_url": self.source_adapter.source_url,
                    "source_schema_version": MODEL_METADATA_SOURCE_SCHEMA_VERSION,
                },
            )


def _source_diagnostics(
    *,
    previous: ModelMetadataSourceSnapshot | None,
    fetched: FetchedModelMetadataSource,
) -> dict[str, object]:
    previous_counts = _provider_counts(previous.payload) if previous is not None else {}
    current_counts = _provider_counts(fetched.payload)
    return {
        "source_kind": fetched.source_kind,
        "source_url": fetched.source_url,
        "source_hash": fetched.source_hash,
        "source_schema_version": fetched.source_schema_version,
        "producer_name": fetched.producer_name,
        "producer_version": fetched.producer_version,
        "provider_count": fetched.provider_count,
        "model_count": fetched.model_count,
        "previous_model_count": previous.model_count if previous is not None else None,
        "supported_provider_counts": current_counts,
        "previous_supported_provider_counts": previous_counts,
    }


def _provider_counts(payload: ModelMetadataSourcePayload) -> dict[str, int]:
    return {
        provider.id: len(provider.models)
        for provider in payload.providers
        if provider.id in _SUPPORTED_PROVIDER_IDS
    }


def _material_reduction(
    *,
    previous: ModelMetadataSourceSnapshot | None,
    fetched: FetchedModelMetadataSource,
) -> str | None:
    if previous is None:
        return None
    removed = previous.model_count - fetched.model_count
    if (
        removed >= _SOURCE_MIN_REMOVAL_COUNT
        and removed / previous.model_count >= _SOURCE_MIN_REMOVAL_RATIO
    ):
        return "global"
    previous_counts = _provider_counts(previous.payload)
    current_counts = _provider_counts(fetched.payload)
    for provider_id, previous_count in previous_counts.items():
        removed = previous_count - current_counts.get(provider_id, 0)
        if (
            removed >= _PROVIDER_MIN_REMOVAL_COUNT
            and removed / previous_count >= _PROVIDER_MIN_REMOVAL_RATIO
        ):
            return f"provider:{provider_id}"
    return None
