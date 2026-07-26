"""Trusted batch Runtime-upload consumer for provider-native delivery."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from azcommon.infra.s3.service import S3ObjectIdentity
from azcommon.uuid import uuid7
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorAdmitTransferRequest,
    CoordinatorAdmitTransferResult,
    CoordinatorCancellationReason,
    CoordinatorCancelTransferRequest,
    CoordinatorConsumerRequest,
    CoordinatorDispatchTransferRequest,
    CoordinatorExpectedManifest,
    CoordinatorGetTransferStatusRequest,
    CoordinatorGetVerifiedObjectRequest,
    CoordinatorGetVerifiedObjectResult,
    CoordinatorMarkTransferReadyRequest,
    CoordinatorObjectManifest,
    CoordinatorSettleTransferRequest,
    CoordinatorTransferDirection,
    CoordinatorTransferOutcome,
    CoordinatorTransferPhase,
    CoordinatorTransferStatus,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget


class RuntimeToProviderTransferError(RuntimeError):
    """Raised when a Runtime source cannot safely reach a provider."""


class RuntimeToProviderCleanupError(RuntimeToProviderTransferError):
    """Raised when pre-provider Runtime cleanup cannot be confirmed."""


class RuntimeToProviderDeliveryExecutor(Protocol):
    """Prepare one trusted Runtime upload batch for a provider-owned delivery."""

    async def prepare(
        self,
        *,
        target: ServerToRuntimeTarget,
        agent_id: str,
        session_id: str,
        operation_id: str,
        batch_id: str,
        sources: tuple[RuntimeToProviderSource, ...],
    ) -> RuntimeToProviderBatch:
        """Prepare the Runtime sources selected for one provider completion."""
        ...


class RuntimeToProviderCoordinator(Protocol):
    """Typed trusted coordinator surface required by provider consumers."""

    async def admit_transfer(
        self,
        request: CoordinatorAdmitTransferRequest,
    ) -> CoordinatorAdmitTransferResult:
        """Admit one Runtime upload attempt."""
        ...

    async def mark_transfer_ready(
        self, request: CoordinatorMarkTransferReadyRequest
    ) -> CoordinatorTransferStatus:
        """Mark one admitted upload object ready."""
        ...

    async def dispatch_transfer(
        self, request: CoordinatorDispatchTransferRequest
    ) -> CoordinatorTransferStatus:
        """Dispatch one typed Runtime upload."""
        ...

    async def get_transfer_status(
        self, request: CoordinatorGetTransferStatusRequest
    ) -> CoordinatorTransferStatus:
        """Read one authoritative transfer status."""
        ...

    async def claim_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        """Claim one verified upload for trusted consumption."""
        ...

    async def get_verified_object(
        self,
        request: CoordinatorGetVerifiedObjectRequest,
    ) -> CoordinatorGetVerifiedObjectResult:
        """Resolve one verified object for an active consumer claim."""
        ...

    async def renew_consumer_lease(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        """Renew one active consumer claim."""
        ...

    async def acknowledge_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        """Acknowledge one consumed verified object."""
        ...

    async def abandon_consumer(
        self, request: CoordinatorConsumerRequest
    ) -> CoordinatorTransferStatus:
        """Abandon one unconsumed verified object."""
        ...

    async def settle_transfer(
        self, request: CoordinatorSettleTransferRequest
    ) -> CoordinatorTransferStatus:
        """Settle one authoritative terminal transfer."""
        ...

    async def cancel_transfer(
        self, request: CoordinatorCancelTransferRequest
    ) -> CoordinatorTransferStatus:
        """Cancel one exact Runtime upload attempt."""
        ...


class VerifiedRuntimeObjectResolver(Protocol):
    """Resolve opaque verified handles only inside trusted backend code."""

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        """Return the internal object identity for one opaque verified handle."""
        ...


class VerifiedRuntimeObjectStore(Protocol):
    """Open a bounded stream for one internally resolved verified object."""

    def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AbstractAsyncContextManager[AsyncIterator[bytes]]:
        """Return an async context manager yielding ordered byte chunks."""
        ...


@dataclass(frozen=True)
class RuntimeToProviderSource:
    """One preflighted Runtime source selected for a provider batch."""

    runtime_path: str
    filename: str
    media_type: str
    expected_size: int


@dataclass(frozen=True)
class RuntimeToProviderBatchRequest:
    """Metadata-only admission request for one provider-owned file batch."""

    target: ServerToRuntimeTarget
    agent_id: str
    session_id: str
    operation_id: str
    batch_id: str
    sources: tuple[RuntimeToProviderSource, ...]
    product_maximum_size: int
    provider_maximum_size: int
    deadline_at: datetime.datetime
    resource_class: str


@dataclass(frozen=True)
class RuntimeToProviderRecovery:
    """Safe persisted correlation for post-provider acknowledgement recovery."""

    transfer_id: str
    attempt_id: str
    consumer_claim_id: str
    revision: int


@dataclass
class _PreparedRuntimeSource:
    """Private active claim and opaque object reference for one batch source."""

    source: RuntimeToProviderSource
    identity: CoordinatorTransferIdentity
    claim_id: str | None
    revision: int
    verified_object_handle: str | None
    verified_size: int | None
    verified_sha256: str | None
    lease_failure: RuntimeToProviderTransferError | None = None
    streamed: bool = False
    renewal_task: asyncio.Task[None] | None = None


class RuntimeToProviderBatch:
    """Live provider batch retaining every Runtime consumer claim until terminal."""

    def __init__(
        self,
        *,
        coordinator: RuntimeToProviderCoordinator,
        resolver: VerifiedRuntimeObjectResolver,
        object_store: VerifiedRuntimeObjectStore,
        clock: Callable[[], datetime.datetime],
        status_poll_interval: datetime.timedelta,
        consumer_lease_renew_interval: datetime.timedelta,
        deadline_at: datetime.datetime,
        sources: list[_PreparedRuntimeSource],
        maximum_chunk_size: int,
    ) -> None:
        self._coordinator = coordinator
        self._resolver = resolver
        self._object_store = object_store
        self._clock = clock
        self._status_poll_interval = status_poll_interval
        self._consumer_lease_renew_interval = consumer_lease_renew_interval
        self._deadline_at = deadline_at
        self._sources = sources
        self._maximum_chunk_size = maximum_chunk_size
        self._provider_completed = False
        self._closed = False

    @property
    def source_count(self) -> int:
        """Return the ordered number of prepared Runtime sources."""
        return len(self._sources)

    async def ensure_active(self) -> None:
        """Fail before provider I/O when any batch claim is no longer usable."""
        if self._closed:
            raise RuntimeToProviderTransferError("Runtime provider batch is closed")
        if self._clock() >= self._deadline_at:
            raise RuntimeToProviderTransferError(
                "Runtime provider batch deadline expired"
            )
        for source in self._sources:
            if source.lease_failure is not None:
                raise source.lease_failure

    async def iter_source_chunks(self, index: int) -> AsyncIterator[bytes]:
        """Yield one verified object once with bounded backpressure and closure."""
        await self.ensure_active()
        source = self._source(index)
        if source.streamed:
            raise RuntimeToProviderTransferError(
                "Runtime provider source was already streamed"
            )
        if source.lease_failure is not None:
            raise source.lease_failure
        if (
            source.verified_object_handle is None
            or source.verified_size is None
            or source.verified_sha256 is None
        ):
            raise RuntimeToProviderTransferError(
                "Runtime provider source is not verified"
            )
        source.streamed = True
        identity = self._resolver.resolve(source.verified_object_handle)
        observed_size = 0
        try:
            async with self._object_store.iter_chunks(
                identity,
                maximum_chunk_size=self._maximum_chunk_size,
            ) as chunks:
                async for chunk in chunks:
                    if source.lease_failure is not None:
                        raise source.lease_failure
                    if self._clock() >= self._deadline_at:
                        raise RuntimeToProviderTransferError(
                            "Runtime provider batch deadline expired during streaming"
                        )
                    if not chunk or len(chunk) > self._maximum_chunk_size:
                        raise RuntimeToProviderTransferError(
                            "Verified Runtime object yielded an invalid chunk"
                        )
                    observed_size += len(chunk)
                    if observed_size > source.verified_size:
                        raise RuntimeToProviderTransferError(
                            "Verified Runtime object exceeded its expected size"
                        )
                    yield chunk
        except asyncio.CancelledError:
            raise
        except FileNotFoundError:
            raise RuntimeToProviderTransferError(
                "Verified Runtime object is unavailable"
            ) from None
        if observed_size != source.verified_size:
            raise RuntimeToProviderTransferError(
                "Verified Runtime object ended before its expected size"
            )

    async def provider_completed(self) -> tuple[RuntimeToProviderRecovery, ...]:
        """Return durable-safe recovery evidence after one provider completion."""
        if self._closed:
            raise RuntimeToProviderTransferError("Runtime provider batch is closed")
        if not all(source.streamed for source in self._sources):
            raise RuntimeToProviderTransferError(
                "Provider completion requires every Runtime source stream"
            )
        for source in self._sources:
            if source.lease_failure is not None:
                raise source.lease_failure
        self._provider_completed = True
        return tuple(
            RuntimeToProviderRecovery(
                transfer_id=source.identity.transfer_id,
                attempt_id=source.identity.attempt_id,
                consumer_claim_id=_required_claim_id(source),
                revision=source.revision,
            )
            for source in self._sources
        )

    async def acknowledge_and_settle(self) -> None:
        """Acknowledge and settle every source after durable provider completion."""
        if not self._provider_completed:
            raise RuntimeToProviderTransferError(
                "Runtime provider acknowledgement requires provider completion"
            )
        for source in self._sources:
            source.revision = await self._acknowledge(source)
        for source in self._sources:
            await self._settle(source)
        await self.close()

    async def abandon_or_cancel(self) -> None:
        """Abandon claimed sources and cancel exact pre-provider upload attempts."""
        if self._provider_completed:
            return
        failure: BaseException | None = None
        for source in self._sources:
            try:
                await self._abandon_or_cancel_source(source)
            except asyncio.CancelledError:
                raise
            except BaseException as error:
                if failure is None:
                    failure = error
        await self.close()
        if failure is not None:
            raise RuntimeToProviderCleanupError(
                "Runtime provider batch cleanup failed"
            ) from failure

    async def close(self) -> None:
        """Stop lease renewal without changing the current transfer outcome."""
        if self._closed:
            return
        self._closed = True
        tasks = [
            source.renewal_task
            for source in self._sources
            if source.renewal_task is not None
        ]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _acknowledge(self, source: _PreparedRuntimeSource) -> int:
        revision = source.revision
        claim_id = _required_claim_id(source)
        while self._clock() < self._deadline_at:
            try:
                status = await self._coordinator.acknowledge_consumer(
                    CoordinatorConsumerRequest(
                        identity=source.identity,
                        expected_revision=revision,
                        consumer_claim_id=claim_id,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                status = await self._observe_status(source.identity)
            if status.phase is CoordinatorTransferPhase.CONSUMED:
                return status.revision
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                if status.outcome is CoordinatorTransferOutcome.SUCCEEDED:
                    return status.revision
                raise RuntimeToProviderTransferError(
                    "Provider-completed Runtime source acknowledgement was rejected"
                )
            revision = status.revision
            await asyncio.sleep(self._status_poll_interval.total_seconds())
        raise RuntimeToProviderTransferError(
            "Provider-completed Runtime source acknowledgement was not confirmed"
        )

    async def _settle(self, source: _PreparedRuntimeSource) -> None:
        revision = source.revision
        while self._clock() < self._deadline_at:
            try:
                status = await self._coordinator.settle_transfer(
                    CoordinatorSettleTransferRequest(
                        identity=source.identity,
                        expected_revision=revision,
                        outcome=CoordinatorTransferOutcome.SUCCEEDED,
                        failure=None,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                status = await self._observe_status(source.identity)
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                if status.outcome is CoordinatorTransferOutcome.SUCCEEDED:
                    return
                raise RuntimeToProviderTransferError(
                    "Provider-completed Runtime source was not settled"
                )
            revision = status.revision
            await asyncio.sleep(self._status_poll_interval.total_seconds())
        raise RuntimeToProviderTransferError(
            "Provider-completed Runtime source settlement was not confirmed"
        )

    async def _abandon_or_cancel_source(self, source: _PreparedRuntimeSource) -> None:
        status = await self._observe_status(source.identity)
        if _cleanup_confirmed(status):
            return
        source.revision = status.revision
        if status.phase is CoordinatorTransferPhase.CONSUMING:
            status = await self._abandon_source_claim(source)
            if _cleanup_confirmed(status):
                return
            if status.phase is CoordinatorTransferPhase.CONSUMING:
                raise RuntimeToProviderCleanupError(
                    "Runtime provider consumer claim could not be abandoned"
                )
            source.revision = status.revision
        await self._cancel_source_attempt(source)

    async def _abandon_source_claim(
        self,
        source: _PreparedRuntimeSource,
    ) -> CoordinatorTransferStatus:
        try:
            return await self._coordinator.abandon_consumer(
                CoordinatorConsumerRequest(
                    identity=source.identity,
                    expected_revision=source.revision,
                    consumer_claim_id=_required_claim_id(source),
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._observe_status(source.identity)

    async def _cancel_source_attempt(self, source: _PreparedRuntimeSource) -> None:
        revision = source.revision
        while self._clock() < self._deadline_at:
            try:
                status = await self._coordinator.cancel_transfer(
                    CoordinatorCancelTransferRequest(
                        identity=source.identity,
                        expected_revision=revision,
                        reason=CoordinatorCancellationReason.CALLER,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                status = await self._observe_status(source.identity)
            if _cleanup_confirmed(status):
                return
            if status.phase is CoordinatorTransferPhase.CONSUMING:
                raise RuntimeToProviderCleanupError(
                    "Runtime provider source became unavailable for cancellation"
                )
            revision = status.revision
            await asyncio.sleep(self._status_poll_interval.total_seconds())
        raise RuntimeToProviderCleanupError(
            "Runtime provider source cancellation was not confirmed"
        )

    async def _observe_status(
        self,
        identity: CoordinatorTransferIdentity,
    ) -> CoordinatorTransferStatus:
        last_error: Exception | None = None
        while self._clock() < self._deadline_at:
            try:
                return await self._coordinator.get_transfer_status(
                    CoordinatorGetTransferStatusRequest(identity=identity)
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                last_error = error
            await asyncio.sleep(self._status_poll_interval.total_seconds())
        raise RuntimeToProviderTransferError(
            "Runtime provider source status could not be observed"
        ) from last_error

    def _source(self, index: int) -> _PreparedRuntimeSource:
        if index < 0 or index >= len(self._sources):
            raise RuntimeToProviderTransferError("Runtime provider source is invalid")
        return self._sources[index]


class RuntimeToProviderBatchService:
    """Prepare verified Runtime uploads for one at-most-once provider batch."""

    def __init__(
        self,
        *,
        coordinator: RuntimeToProviderCoordinator,
        resolver: VerifiedRuntimeObjectResolver,
        object_store: VerifiedRuntimeObjectStore,
        clock: Callable[[], datetime.datetime],
        status_poll_interval: datetime.timedelta,
        consumer_lease_renew_interval: datetime.timedelta,
        maximum_chunk_size: int,
    ) -> None:
        self.coordinator = coordinator
        self.resolver = resolver
        self.object_store = object_store
        self.clock = clock
        self.status_poll_interval = status_poll_interval
        self.consumer_lease_renew_interval = consumer_lease_renew_interval
        self.maximum_chunk_size = maximum_chunk_size

    async def prepare(
        self,
        request: RuntimeToProviderBatchRequest,
    ) -> RuntimeToProviderBatch:
        """Admit, upload, verify, claim, and renew every source before provider I/O."""
        self._validate(request)
        prepared: list[_PreparedRuntimeSource] = []
        try:
            for index, source in enumerate(request.sources):
                await self._prepare_source(
                    request=request,
                    source=source,
                    index=index,
                    prepared=prepared,
                )
            batch = RuntimeToProviderBatch(
                coordinator=self.coordinator,
                resolver=self.resolver,
                object_store=self.object_store,
                clock=self.clock,
                status_poll_interval=self.status_poll_interval,
                consumer_lease_renew_interval=self.consumer_lease_renew_interval,
                deadline_at=request.deadline_at,
                sources=prepared,
                maximum_chunk_size=self.maximum_chunk_size,
            )
            for source in prepared:
                source.renewal_task = asyncio.create_task(
                    self._renew_consumer_lease(
                        source=source,
                        deadline_at=request.deadline_at,
                    )
                )
            return batch
        except asyncio.CancelledError:
            try:
                await _cleanup_prepared_sources(
                    coordinator=self.coordinator,
                    prepared=prepared,
                    clock=self.clock,
                    deadline_at=request.deadline_at,
                    status_poll_interval=self.status_poll_interval,
                )
            except RuntimeToProviderTransferError:
                pass
            raise
        except Exception:
            await _cleanup_prepared_sources(
                coordinator=self.coordinator,
                prepared=prepared,
                clock=self.clock,
                deadline_at=request.deadline_at,
                status_poll_interval=self.status_poll_interval,
            )
            raise

    async def _prepare_source(
        self,
        *,
        request: RuntimeToProviderBatchRequest,
        source: RuntimeToProviderSource,
        index: int,
        prepared: list[_PreparedRuntimeSource],
    ) -> _PreparedRuntimeSource:
        identity = CoordinatorTransferIdentity(
            transfer_id=uuid7().hex,
            attempt_id=uuid7().hex,
            runtime_id=request.target.runtime_id,
            desired_generation=request.target.desired_generation,
            direction=CoordinatorTransferDirection.UPLOAD.value,
            operation_id=f"{request.operation_id}:{index}",
            session_id=request.session_id,
            agent_id=request.agent_id,
        )
        admitted = await self.coordinator.admit_transfer(
            CoordinatorAdmitTransferRequest(
                identity=identity,
                lease_id=uuid7().hex,
                runtime_path=source.runtime_path,
                overwrite=False,
                expected_manifest=CoordinatorExpectedManifest(
                    size=source.expected_size,
                    sha256=None,
                ),
                product_maximum_size=request.product_maximum_size,
                provider_maximum_size=request.provider_maximum_size,
                deadline_at=request.deadline_at,
                source_expires_at=None,
                resource_class=request.resource_class,
            )
        )
        prepared_source = _PreparedRuntimeSource(
            source=source,
            identity=identity,
            claim_id=None,
            revision=admitted.status.revision,
            verified_object_handle=None,
            verified_size=None,
            verified_sha256=None,
        )
        prepared.append(prepared_source)
        ready = await self.coordinator.mark_transfer_ready(
            CoordinatorMarkTransferReadyRequest(
                identity=identity,
                expected_revision=prepared_source.revision,
                object_handle=admitted.admitted_object_handle,
                object_manifest=CoordinatorObjectManifest(
                    size=source.expected_size,
                    sha256=None,
                ),
            )
        )
        prepared_source.revision = ready.revision
        await self.coordinator.dispatch_transfer(
            CoordinatorDispatchTransferRequest(
                identity=identity,
                expected_revision=prepared_source.revision,
                dispatch_id=uuid7().hex,
            )
        )
        available = await self._wait_available(identity, request.deadline_at)
        claim_id = uuid7().hex
        claimed = await self.coordinator.claim_consumer(
            CoordinatorConsumerRequest(
                identity=identity,
                expected_revision=available.revision,
                consumer_claim_id=claim_id,
            )
        )
        prepared_source.claim_id = claim_id
        prepared_source.revision = claimed.revision
        verified = await self.coordinator.get_verified_object(
            CoordinatorGetVerifiedObjectRequest(
                identity=identity,
                expected_revision=prepared_source.revision,
                consumer_claim_id=claim_id,
            )
        )
        renewed = await self.coordinator.renew_consumer_lease(
            CoordinatorConsumerRequest(
                identity=identity,
                expected_revision=verified.status.revision,
                consumer_claim_id=claim_id,
            )
        )
        manifest = verified.actual_manifest
        if (
            manifest.size is None
            or manifest.sha256 is None
            or manifest.size != source.expected_size
        ):
            raise RuntimeToProviderTransferError(
                "Verified Runtime provider source does not match preflight"
            )
        prepared_source.revision = renewed.revision
        prepared_source.verified_object_handle = verified.verified_object_handle.value
        prepared_source.verified_size = manifest.size
        prepared_source.verified_sha256 = manifest.sha256
        return prepared_source

    async def _wait_available(
        self,
        identity: CoordinatorTransferIdentity,
        deadline_at: datetime.datetime,
    ) -> CoordinatorTransferStatus:
        while self.clock() < deadline_at:
            status = await self.coordinator.get_transfer_status(
                CoordinatorGetTransferStatusRequest(identity=identity)
            )
            if status.phase is CoordinatorTransferPhase.AVAILABLE:
                return status
            if status.phase is CoordinatorTransferPhase.TERMINAL:
                raise RuntimeToProviderTransferError(
                    "Runtime provider source terminated before consumption"
                )
            await asyncio.sleep(self.status_poll_interval.total_seconds())
        raise RuntimeToProviderTransferError(
            "Runtime provider source deadline expired before consumption"
        )

    async def _renew_consumer_lease(
        self,
        *,
        source: _PreparedRuntimeSource,
        deadline_at: datetime.datetime,
    ) -> None:
        while True:
            await asyncio.sleep(self.consumer_lease_renew_interval.total_seconds())
            if self.clock() >= deadline_at:
                source.lease_failure = RuntimeToProviderTransferError(
                    "Runtime provider source deadline expired"
                )
                return
            try:
                status = await self.coordinator.renew_consumer_lease(
                    CoordinatorConsumerRequest(
                        identity=source.identity,
                        expected_revision=source.revision,
                        consumer_claim_id=_required_claim_id(source),
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                source.lease_failure = RuntimeToProviderTransferError(
                    "Runtime provider consumer lease renewal failed"
                )
                return
            if status.phase is not CoordinatorTransferPhase.CONSUMING:
                source.lease_failure = RuntimeToProviderTransferError(
                    "Runtime provider consumer lease was lost"
                )
                return
            source.revision = status.revision

    def _validate(self, request: RuntimeToProviderBatchRequest) -> None:
        if not request.sources:
            raise ValueError("Runtime provider batch requires at least one source")
        if self.maximum_chunk_size <= 0:
            raise ValueError("Runtime provider maximum_chunk_size must be positive")
        if self.clock() >= request.deadline_at:
            raise RuntimeToProviderTransferError(
                "Runtime provider batch deadline expired"
            )
        total_size = 0
        for source in request.sources:
            if source.expected_size <= 0:
                raise ValueError("Runtime provider source size must be positive")
            total_size += source.expected_size
        if total_size > request.provider_maximum_size:
            raise ValueError("Runtime provider batch exceeds provider maximum size")


class RuntimeToProviderDeliveryService:
    """Bind provider delivery policy around the verified Runtime batch service."""

    def __init__(
        self,
        *,
        batch_service: RuntimeToProviderBatchService,
        product_maximum_size: int,
        provider_maximum_size: int,
        deadline: datetime.timedelta,
        resource_class: str,
    ) -> None:
        if product_maximum_size <= 0 or provider_maximum_size <= 0:
            raise ValueError("Runtime provider delivery limits must be positive")
        if deadline <= datetime.timedelta():
            raise ValueError("Runtime provider delivery deadline must be positive")
        if not resource_class:
            raise ValueError("Runtime provider delivery resource class is required")
        self.batch_service = batch_service
        self.product_maximum_size = product_maximum_size
        self.provider_maximum_size = provider_maximum_size
        self.deadline = deadline
        self.resource_class = resource_class

    async def prepare(
        self,
        *,
        target: ServerToRuntimeTarget,
        agent_id: str,
        session_id: str,
        operation_id: str,
        batch_id: str,
        sources: tuple[RuntimeToProviderSource, ...],
    ) -> RuntimeToProviderBatch:
        """Prepare one bounded provider batch using trusted configured limits."""
        return await self.batch_service.prepare(
            RuntimeToProviderBatchRequest(
                target=target,
                agent_id=agent_id,
                session_id=session_id,
                operation_id=operation_id,
                batch_id=batch_id,
                sources=sources,
                product_maximum_size=self.product_maximum_size,
                provider_maximum_size=self.provider_maximum_size,
                deadline_at=self.batch_service.clock() + self.deadline,
                resource_class=self.resource_class,
            )
        )


@dataclass(frozen=True)
class RuntimeToProviderDeliveryCapability:
    """Bind one trusted provider-delivery service to the current Runtime run."""

    service: RuntimeToProviderDeliveryExecutor
    target: ServerToRuntimeTarget
    agent_id: str
    session_id: str

    async def prepare(
        self,
        *,
        operation_id: str,
        batch_id: str,
        sources: tuple[RuntimeToProviderSource, ...],
    ) -> RuntimeToProviderBatch:
        """Prepare one provider batch without exposing storage implementation data."""
        return await self.service.prepare(
            target=self.target,
            agent_id=self.agent_id,
            session_id=self.session_id,
            operation_id=operation_id,
            batch_id=batch_id,
            sources=sources,
        )


async def _cleanup_prepared_sources(
    *,
    coordinator: RuntimeToProviderCoordinator,
    prepared: Sequence[_PreparedRuntimeSource],
    clock: Callable[[], datetime.datetime],
    deadline_at: datetime.datetime,
    status_poll_interval: datetime.timedelta,
) -> None:
    """Abandon or cancel each exact source after pre-provider preparation fails."""
    failure: BaseException | None = None
    for source in reversed(prepared):
        try:
            await _cleanup_prepared_source(
                coordinator=coordinator,
                source=source,
                clock=clock,
                deadline_at=deadline_at,
                status_poll_interval=status_poll_interval,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            if failure is None:
                failure = error
    if failure is not None:
        raise RuntimeToProviderCleanupError(
            "Runtime provider preparation cleanup failed"
        ) from failure


async def _cleanup_prepared_source(
    *,
    coordinator: RuntimeToProviderCoordinator,
    source: _PreparedRuntimeSource,
    clock: Callable[[], datetime.datetime],
    deadline_at: datetime.datetime,
    status_poll_interval: datetime.timedelta,
) -> None:
    """Confirm one pre-provider attempt is abandoned or cancellation-requested."""
    status = await _observe_source_status(
        coordinator=coordinator,
        identity=source.identity,
        clock=clock,
        deadline_at=deadline_at,
        status_poll_interval=status_poll_interval,
    )
    if _cleanup_confirmed(status):
        return
    source.revision = status.revision
    if status.phase is CoordinatorTransferPhase.CONSUMING:
        try:
            status = await coordinator.abandon_consumer(
                CoordinatorConsumerRequest(
                    identity=source.identity,
                    expected_revision=source.revision,
                    consumer_claim_id=_required_claim_id(source),
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            status = await _observe_source_status(
                coordinator=coordinator,
                identity=source.identity,
                clock=clock,
                deadline_at=deadline_at,
                status_poll_interval=status_poll_interval,
            )
        if _cleanup_confirmed(status):
            return
        if status.phase is CoordinatorTransferPhase.CONSUMING:
            raise RuntimeToProviderCleanupError(
                "Runtime provider consumer claim could not be abandoned"
            )
        source.revision = status.revision
    revision = source.revision
    while clock() < deadline_at:
        try:
            status = await coordinator.cancel_transfer(
                CoordinatorCancelTransferRequest(
                    identity=source.identity,
                    expected_revision=revision,
                    reason=CoordinatorCancellationReason.CALLER,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            status = await _observe_source_status(
                coordinator=coordinator,
                identity=source.identity,
                clock=clock,
                deadline_at=deadline_at,
                status_poll_interval=status_poll_interval,
            )
        if _cleanup_confirmed(status):
            return
        if status.phase is CoordinatorTransferPhase.CONSUMING:
            raise RuntimeToProviderCleanupError(
                "Runtime provider source became unavailable for cancellation"
            )
        revision = status.revision
        await asyncio.sleep(status_poll_interval.total_seconds())
    raise RuntimeToProviderCleanupError(
        "Runtime provider source cancellation was not confirmed"
    )


async def _observe_source_status(
    *,
    coordinator: RuntimeToProviderCoordinator,
    identity: CoordinatorTransferIdentity,
    clock: Callable[[], datetime.datetime],
    deadline_at: datetime.datetime,
    status_poll_interval: datetime.timedelta,
) -> CoordinatorTransferStatus:
    """Observe one authoritative source status before exact cleanup."""
    last_error: Exception | None = None
    while clock() < deadline_at:
        try:
            return await coordinator.get_transfer_status(
                CoordinatorGetTransferStatusRequest(identity=identity)
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            last_error = error
        await asyncio.sleep(status_poll_interval.total_seconds())
    raise RuntimeToProviderCleanupError(
        "Runtime provider source status could not be observed for cleanup"
    ) from last_error


def _cleanup_confirmed(status: CoordinatorTransferStatus) -> bool:
    """Return whether authoritative state has accepted terminal cleanup."""
    return (
        status.phase is CoordinatorTransferPhase.TERMINAL
        or status.cancellation_requested
    )


def _required_claim_id(source: _PreparedRuntimeSource) -> str:
    claim_id = source.claim_id
    if claim_id is None:
        raise RuntimeToProviderTransferError("Runtime provider source claim is missing")
    return claim_id
