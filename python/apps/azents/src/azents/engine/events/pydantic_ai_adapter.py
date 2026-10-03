"""Public model transport with native progress and engine-owned watchdogs."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from typing import assert_never

from azents.engine.events.pydantic_ai_types import (
    PydanticAIRequest,
    PydanticAIStreamEvent,
)
from azents.engine.model_stream import (
    ModelDispatchAdmissionError,
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
)
from azents.engine.providers.model_factory import ProviderModelFactory
from azents.engine.providers.observation_state import (
    InternalModelExecutionError,
    NativeObservationState,
    StreamFailure,
    StreamFinished,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    UnclassifiedModelProviderError,
)


class _ModelEventStream:
    """One producer's bounded stream and strongly owned cleanup lifetime."""

    def __init__(
        self,
        *,
        state: NativeObservationState,
        producer: asyncio.Task[None],
    ) -> None:
        self.state = state
        self.producer = producer
        self.exhausted = False
        self.close_task: asyncio.Task[None] | None = None

    def __aiter__(self) -> "_ModelEventStream":
        return self

    async def __anext__(self) -> PydanticAIStreamEvent:
        if self.exhausted:
            raise StopAsyncIteration
        item = await self.state.queue.get()
        match item:
            case PydanticAIStreamEvent():
                return item
            case StreamFailure(error=error):
                raise error from None
            case StreamFinished():
                self.exhausted = True
                raise StopAsyncIteration
            case _:
                assert_never(item)

    async def aclose(self) -> None:
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close())
        await asyncio.shield(self.close_task)

    async def _close(self) -> None:
        self.state.begin_close()
        if not self.producer.done() and not self.exhausted:
            self.producer.cancel()
        try:
            for close in reversed(self.state.close_callbacks):
                await close()
            await self.producer
        except asyncio.CancelledError:
            pass
        except Exception as error:
            raise InternalModelExecutionError(
                origin_type=type(error).__name__
            ).with_traceback(error.__traceback__) from None
        finally:
            await self.state.wait_for_worker()


class PydanticAIModelAdapter:
    """Execute models without introducing an Agent graph or hidden retries."""

    def __init__(self, *, factory: ProviderModelFactory) -> None:
        self.factory = factory
        self.active: set[_ModelEventStream] = set()

    async def stream(
        self,
        request: PydanticAIRequest,
        *,
        watchdog: ModelStreamWatchdog,
        timeout_policy: ModelStreamTimeoutPolicy,
        call_context: ModelStreamCallContext,
    ) -> AsyncIterator[PydanticAIStreamEvent]:
        if request.provider != self.factory.provider.value:
            raise ValueError("The model request does not match its integration.")
        state = NativeObservationState(
            protocol=self.factory.protocol(model=request.model),
            call_context=call_context,
            timeout_policy=timeout_policy,
            sdk_failure_mapper=self.factory.sdk_failure_mapper,
        )
        producer = asyncio.create_task(self._produce(request=request, state=state))
        handle = _ModelEventStream(state=state, producer=producer)
        self.active.add(handle)

        async def acquire() -> _ModelEventStream:
            try:
                await asyncio.shield(state.response_acquired)
            except asyncio.CancelledError:
                await handle.aclose()
                raise
            return handle

        cancelled = False
        try:
            watched = await watchdog.open_response(
                acquire,
                policy=timeout_policy,
                context=call_context,
                parsed_event_activity=_parsed_native_activity,
            )
            if not isinstance(watched, AsyncIterable):
                raise TypeError("The model watchdog did not return a stream.")
            async for item in watched:
                if not isinstance(item, PydanticAIStreamEvent):
                    raise TypeError("The model stream emitted an invalid event.")
                yield item
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            await self._finish_stream(
                handle,
                watchdog=watchdog,
                call_context=call_context,
                cancelled=cancelled,
            )

    async def _finish_stream(
        self,
        handle: _ModelEventStream,
        *,
        watchdog: ModelStreamWatchdog,
        call_context: ModelStreamCallContext,
        cancelled: bool,
    ) -> None:
        close = asyncio.create_task(handle.aclose())
        self.active.discard(handle)
        if cancelled:
            # User Stop/cancellation does not spend a new close-grace wait.
            # Strong process ownership keeps the actual SDK resource observable.
            watchdog.cleanup_registry.adopt(
                close, context=call_context, reason="caller_cancelled"
            )
            return
        grace = asyncio.create_task(watchdog.clock.sleep(watchdog.close_grace_seconds))
        try:
            done, _ = await asyncio.wait(
                {close, grace}, return_when=asyncio.FIRST_COMPLETED
            )
            if close in done:
                if not close.cancelled() and close.exception() is not None:
                    watchdog.cleanup_registry.adopt(
                        close, context=call_context, reason="caller_cancelled"
                    )
            else:
                watchdog.cleanup_registry.adopt(
                    close, context=call_context, reason="caller_cancelled"
                )
        except asyncio.CancelledError:
            watchdog.cleanup_registry.adopt(
                close, context=call_context, reason="caller_cancelled"
            )
            raise
        finally:
            grace.cancel()

    async def _produce(
        self, *, request: PydanticAIRequest, state: NativeObservationState
    ) -> None:
        binding = None
        manager = None
        entered = False
        try:
            binding = await self.factory.create(
                model=request.model,
                assembly_metadata=request.assembly_metadata,
                state=state,
            )
            manager = binding.model.request_stream(
                request.messages, request.settings, request.parameters
            )
            stream = await manager.__aenter__()
            entered = True
            async for event in stream:
                await state.emit(
                    PydanticAIStreamEvent(event=event, response=None, observation=None)
                )
            await state.emit(
                PydanticAIStreamEvent(
                    event=None, response=stream.get(), observation=None
                )
            )
            await state.emit(StreamFinished())
        except asyncio.CancelledError:
            raise
        except (
            ModelProviderFailure,
            UnclassifiedModelProviderError,
            ModelDispatchAdmissionError,
        ) as error:
            state.fail_acquisition(error)
            if not state.closing:
                await state.emit(StreamFailure(error=error))
        except self.factory.sdk_error_types as error:
            if state.dispatch_blocked:
                safe = state.original_failure or InternalModelExecutionError(
                    origin_type="UnauthorizedModelDispatchError"
                )
            else:
                try:
                    safe = self.factory.sdk_failure_mapper(
                        error, call_context=state.call_context
                    )
                except UnclassifiedModelProviderError as unclassified:
                    safe = unclassified
            if isinstance(safe, ModelProviderFailure | UnclassifiedModelProviderError):
                state.original_failure = safe
            state.fail_acquisition(safe)
            if not state.closing:
                await state.emit(StreamFailure(error=safe))
        except Exception as error:
            safe = InternalModelExecutionError(
                origin_type=type(error).__name__
            ).with_traceback(error.__traceback__)
            state.fail_acquisition(safe)
            if not state.closing:
                await state.emit(StreamFailure(error=safe))
        finally:
            if manager is not None and entered:
                await manager.__aexit__(None, None, None)
            if binding is not None:
                await binding.close()

    async def close(self) -> None:
        """Request cancellation; stream/watchdog ownership bounds the close."""
        for handle in tuple(self.active):
            handle.producer.cancel()


def _parsed_native_activity(event: object) -> bool:
    """Only parsed native progress owns the provider idle clock."""
    return (
        isinstance(event, PydanticAIStreamEvent)
        and event.observation is not None
        and event.observation.parsed_activity
    )
