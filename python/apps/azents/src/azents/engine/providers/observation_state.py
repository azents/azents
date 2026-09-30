"""Bounded operation-owned progress and physical-dispatch control."""

import asyncio
import dataclasses
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future

from pydantic_ai.exceptions import ModelHTTPError

from azents.engine.events.pydantic_ai_types import (
    NativeModelObservation,
    NativeModelProtocol,
    PydanticAIStreamEvent,
    SDKFailureMapper,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
)
from azents.engine.providers.native_observation import observe_native_payload
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    UnclassifiedModelProviderError,
)


class UnauthorizedModelDispatchError(RuntimeError):
    """An internal model attempted an unapproved second generation request."""

    def __init__(self) -> None:
        super().__init__("The model attempted an unauthorized inference dispatch.")


class InternalModelExecutionError(RuntimeError):
    """Preserve origin frames without rendering an untrusted exception body."""

    def __init__(self, *, origin_type: str) -> None:
        self.origin_type = origin_type
        super().__init__("The provider model failed internally.")


@dataclasses.dataclass(frozen=True, repr=False)
class StreamFailure:
    """A safely raised producer failure, never a successful model result."""

    error: Exception


@dataclasses.dataclass(frozen=True)
class StreamFinished:
    """The model assembler exhausted after emitting its final response."""


type StreamQueueItem = PydanticAIStreamEvent | StreamFailure | StreamFinished


class NativeObservationState:
    """One bounded producer/consumer channel and one generation authorization."""

    def __init__(
        self,
        *,
        protocol: NativeModelProtocol,
        call_context: ModelStreamCallContext,
        timeout_policy: ModelStreamTimeoutPolicy,
        sdk_failure_mapper: SDKFailureMapper,
    ) -> None:
        self.protocol = protocol
        self.call_context = call_context
        self.timeout_policy = timeout_policy
        self.sdk_failure_mapper = sdk_failure_mapper
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[StreamQueueItem] = asyncio.Queue(maxsize=1)
        self.response_acquired: asyncio.Future[None] = self.loop.create_future()
        self.dispatch_count = 0
        self.dispatch_blocked = False
        self.response_retry_after: str | None = None
        self.original_failure: (
            ModelProviderFailure | UnclassifiedModelProviderError | None
        ) = None
        self.closing = False
        self.close_callbacks: list[Callable[[], Awaitable[None]]] = []
        self.thread_emissions: set[Future[None]] = set()
        self.thread_lock = threading.Lock()
        self.worker_completion: Future[None] | None = None
        self.native_failure: NativeModelObservation | None = None

    def worker_started(self) -> None:
        """Retain public SDK work even if its async waiter is cancelled."""
        with self.thread_lock:
            self.worker_completion = Future()

    def worker_finished(self) -> None:
        """Complete ownership after a public response/error hook has settled."""
        with self.thread_lock:
            completion = self.worker_completion
            if completion is not None and not completion.done():
                completion.set_result(None)

    async def wait_for_worker(self) -> None:
        """Keep registered cleanup alive until the synchronous SDK has returned."""
        with self.thread_lock:
            completion = self.worker_completion
        if completion is not None:
            await asyncio.shield(asyncio.wrap_future(completion))

    def authorize_dispatch(self) -> None:
        """Reject hidden recovery before it can issue another inference I/O."""
        if self.dispatch_count:
            self.dispatch_blocked = True
            if self.original_failure is not None:
                raise self.original_failure from None
            raise UnauthorizedModelDispatchError() from None
        self.dispatch_count += 1

    def acquired(self) -> None:
        """Signal real SDK response acquisition, before stock first-event peeks."""
        if not self.response_acquired.done():
            self.response_acquired.set_result(None)

    def acquired_from_thread(self) -> None:
        """Hand a public cloud SDK response signal to the owning event loop."""
        self.loop.call_soon_threadsafe(self.acquired)

    def retain_http_failure(
        self, *, status_code: int, body: object
    ) -> ModelProviderFailure | UnclassifiedModelProviderError:
        """Retain the original safe failure before model recovery can catch it."""
        error = ModelHTTPError(
            status_code=status_code,
            model_name=self.call_context.model,
            body=body,
            headers=(
                {"retry-after": self.response_retry_after}
                if self.response_retry_after is not None
                else None
            ),
        )
        try:
            safe = self.sdk_failure_mapper(error, call_context=self.call_context)
        except UnclassifiedModelProviderError as failure:
            safe = failure
        self.original_failure = safe
        return safe

    async def emit(self, item: StreamQueueItem) -> None:
        """Apply backpressure without introducing a second unbounded stream."""
        if self.closing:
            raise asyncio.CancelledError
        await self.queue.put(item)

    async def observe(self, payload: dict[str, object]) -> None:
        """Expose all parsed native events, including nonsemantic activity."""
        observation = observe_native_payload(self.protocol, payload)
        if self.native_failure is None and (
            observation.terminal in {"failed", "incomplete"}
            or observation.error is not None
        ):
            self.native_failure = observation
        elif self.native_failure is not None and (
            observation.terminal is not None or observation.error is not None
        ):
            observation = dataclasses.replace(
                observation,
                terminal=self.native_failure.terminal,
                error=self.native_failure.error,
            )
        await self.emit(
            PydanticAIStreamEvent(
                event=None,
                response=None,
                observation=observation,
            )
        )

    def observe_from_thread(self, payload: dict[str, object]) -> None:
        """Backpressure a synchronous SDK iterator on the same bounded channel."""
        future = asyncio.run_coroutine_threadsafe(self.observe(payload), self.loop)
        with self.thread_lock:
            if self.closing:
                future.cancel()
            else:
                self.thread_emissions.add(future)
        try:
            future.result()
        finally:
            with self.thread_lock:
                self.thread_emissions.discard(future)

    def begin_close(self) -> None:
        """Release a worker waiting on queue backpressure after its caller left."""
        with self.thread_lock:
            self.closing = True
            pending = tuple(self.thread_emissions)
        for future in pending:
            future.cancel()

    def fail_acquisition(self, error: Exception) -> None:
        """Propagate an early failure without an orphaned failed Future."""
        if not self.response_acquired.done():
            self.response_acquired.set_exception(error)
            self.response_acquired.add_done_callback(_consume_future_failure)


def _consume_future_failure(future: asyncio.Future[None]) -> None:
    if not future.cancelled():
        future.exception()
