import asyncio
from unittest.mock import AsyncMock

import pytest

from .emitter import EventEmitter, EventEmitterBuilder
from .event import Event


class TestEventEmitter:
    """Tests for EventEmitter."""

    @pytest.mark.asyncio
    async def test_basic_emit_and_listen(self) -> None:
        """Emit an event to one registered listener."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")
        mock_listener = AsyncMock()

        emitter = EventEmitter.builder().listen(test_event, mock_listener).build()

        test_payload = {"data": "test"}
        await emitter.emit(test_event, test_payload)

        mock_listener.assert_called_once_with(test_payload)

    @pytest.mark.asyncio
    async def test_multiple_listeners(self) -> None:
        """Emit an event to multiple registered listeners."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")

        mock_listener1 = AsyncMock()
        mock_listener2 = AsyncMock()
        mock_listener3 = AsyncMock()

        emitter = (
            EventEmitter.builder()
            .listen(test_event, mock_listener1)
            .listen(test_event, mock_listener2)
            .listen(test_event, mock_listener3)
            .build()
        )

        test_payload = {"data": "test"}
        await emitter.emit(test_event, test_payload)

        mock_listener1.assert_called_once_with(test_payload)
        mock_listener2.assert_called_once_with(test_payload)
        mock_listener3.assert_called_once_with(test_payload)

    @pytest.mark.asyncio
    async def test_multiple_events(self) -> None:
        """Emit distinct events to their respective listeners."""
        event1 = Event[dict[str, str]]("namespace1", "event1")
        event2 = Event[dict[str, str]]("namespace2", "event2")

        listener1 = AsyncMock()
        listener2 = AsyncMock()

        emitter = (
            EventEmitter.builder()
            .listen(event1, listener1)
            .listen(event2, listener2)
            .build()
        )

        payload1 = {"data": "event1"}
        payload2 = {"data": "event2"}

        await emitter.emit(event1, payload1)
        await emitter.emit(event2, payload2)

        listener1.assert_called_once_with(payload1)
        listener2.assert_called_once_with(payload2)

    @pytest.mark.asyncio
    async def test_listener_exception_handling(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Continue emitting after a listener raises an exception."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")

        async def failing_listener(payload: dict[str, str]) -> None:
            raise ValueError("Test exception")

        working_listener = AsyncMock()

        emitter = (
            EventEmitter.builder()
            .listen(test_event, failing_listener)
            .listen(test_event, working_listener)
            .build()
        )

        test_payload = {"data": "test"}
        await emitter.emit(test_event, test_payload)

        working_listener.assert_called_once_with(test_payload)

        assert "Background listener task failed" in caplog.text
        assert "Test exception" in caplog.text

    @pytest.mark.asyncio
    async def test_duplicate_event_registration(self) -> None:
        """Register multiple listeners for the same event."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")

        listener1 = AsyncMock()
        listener2 = AsyncMock()

        emitter = (
            EventEmitter.builder()
            .listen(test_event, listener1)
            .listen(test_event, listener2)
            .build()
        )

        test_payload = {"data": "test"}
        await emitter.emit(test_event, test_payload)

        listener1.assert_called_once_with(test_payload)
        listener2.assert_called_once_with(test_payload)

    @pytest.mark.asyncio
    async def test_different_events_same_key(self) -> None:
        """Reject different event objects that share the same key."""
        event1 = Event[dict[str, str]]("test_namespace", "test_event")
        event2 = Event[dict[str, str]]("test_namespace", "test_event")

        listener = AsyncMock()

        with pytest.raises(
            ValueError, match="Cannot register different events with the same key"
        ):
            (
                EventEmitter.builder()
                .listen(event1, listener)
                .listen(event2, listener)
                .build()
            )

    @pytest.mark.asyncio
    async def test_concurrent_emits(self) -> None:
        """Serialize concurrent emissions of the same event."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")

        mock_listener = AsyncMock()

        emitter = EventEmitter.builder().listen(test_event, mock_listener).build()

        payloads = [{"data": f"test_{i}"} for i in range(5)]

        await asyncio.gather(
            *[emitter.emit(test_event, payload) for payload in payloads]
        )

        assert mock_listener.call_count == 5
        for payload in payloads:
            mock_listener.assert_any_call(payload)

    @pytest.mark.asyncio
    async def test_empty_listeners(self) -> None:
        """Ignore events that have no registered listeners."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")

        emitter = EventEmitter.builder().build()

        test_payload = {"data": "test"}
        await emitter.emit(test_event, test_payload)

    @pytest.mark.asyncio
    async def test_builder_pattern(self) -> None:
        """Build an emitter through the fluent builder API."""
        event1 = Event[dict[str, str]]("namespace1", "event1")
        event2 = Event[dict[str, str]]("namespace2", "event2")

        listener1 = AsyncMock()
        listener2 = AsyncMock()

        builder = EventEmitter.builder()
        assert isinstance(builder, EventEmitterBuilder)

        builder = builder.listen(event1, listener1)
        builder = builder.listen(event2, listener2)

        emitter = builder.build()
        assert isinstance(emitter, EventEmitter)

        payload1 = {"data": "event1"}
        payload2 = {"data": "event2"}

        await emitter.emit(event1, payload1)
        await emitter.emit(event2, payload2)

        listener1.assert_called_once_with(payload1)
        listener2.assert_called_once_with(payload2)

    @pytest.mark.asyncio
    async def test_event_key_property(self) -> None:
        """Compose an event key from its namespace and name."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")

        assert test_event.key == "test_namespace:test_event"

        mock_listener = AsyncMock()

        emitter = EventEmitter.builder().listen(test_event, mock_listener).build()

        test_payload = {"data": "test"}
        await emitter.emit(test_event, test_payload)

        mock_listener.assert_called_once_with(test_payload)

    @pytest.mark.asyncio
    async def test_circular_event_emission_detection(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Detect and log circular event emission."""
        test_event = Event[dict[str, str]]("test_namespace", "test_event")

        async def circular_listener(payload: dict[str, str]) -> None:
            await emitter.emit(test_event, {"data": "circular"})

        normal_listener = AsyncMock()

        emitter = (
            EventEmitter.builder()
            .listen(test_event, circular_listener)
            .listen(test_event, normal_listener)
            .build()
        )

        test_payload = {"data": "test"}
        with caplog.at_level("ERROR"):
            await emitter.emit(test_event, test_payload)

        normal_listener.assert_called_once_with(test_payload)
        assert "Circular event emission detected" in caplog.text

    @pytest.mark.asyncio
    async def test_builder_update(self) -> None:
        """Merge two compatible EventEmitterBuilder instances."""
        event1 = Event[dict[str, str]]("namespace1", "event1")
        event2 = Event[dict[str, str]]("namespace2", "event2")
        event3 = Event[dict[str, str]]("namespace3", "event3")

        listener1 = AsyncMock()
        listener2_1 = AsyncMock()
        listener2_2 = AsyncMock()
        listener3 = AsyncMock()

        builder1 = (
            EventEmitter.builder().listen(event1, listener1).listen(event2, listener2_1)
        )

        builder2 = (
            EventEmitter.builder().listen(event2, listener2_2).listen(event3, listener3)
        )

        merged_builder = builder1.update(builder2)

        emitter = merged_builder.build()

        payload1 = {"data": "event1"}
        payload2 = {"data": "event2"}
        payload3 = {"data": "event3"}

        await emitter.emit(event1, payload1)
        await emitter.emit(event2, payload2)
        await emitter.emit(event3, payload3)

        listener1.assert_called_once_with(payload1)
        listener2_1.assert_called_once_with(payload2)
        listener2_2.assert_called_once_with(payload2)
        listener3.assert_called_once_with(payload3)

    @pytest.mark.asyncio
    async def test_builder_update_conflict(self) -> None:
        """Reject merging builders with conflicting event definitions."""
        event1 = Event[dict[str, str]]("test_namespace", "test_event")
        event2 = Event[dict[str, str]]("test_namespace", "test_event")

        listener1 = AsyncMock()
        listener2 = AsyncMock()

        builder1 = EventEmitter.builder().listen(event1, listener1)
        builder2 = EventEmitter.builder().listen(event2, listener2)

        with pytest.raises(
            ValueError,
            match="Cannot update builders with different events with the same key",
        ):
            builder1.update(builder2)
