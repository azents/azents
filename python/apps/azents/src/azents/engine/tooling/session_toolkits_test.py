"""Session toolkit lifecycle tests."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.tooling.session_toolkits import (
    DuplicateSessionToolkitKeyError,
    SessionToolkitBinding,
    SessionToolkitKey,
    SessionToolkitLifecycle,
    SessionToolkitLifecycleClosedError,
)


class _Config(BaseModel):
    """Test toolkit config."""


class _TrackingToolkit(Toolkit[_Config]):
    """Toolkit test double that records lifecycle calls."""

    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail_enter: bool = False,
    ) -> None:
        self.name = name
        self.events = events
        self.fail_enter = fail_enter
        self.update_context_calls = 0

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Record update_context calls."""
        del context
        self.update_context_calls += 1
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    async def __aenter__(self) -> "_TrackingToolkit":
        """Record enter and optionally fail."""
        self.events.append(f"enter:{self.name}")
        if self.fail_enter:
            raise RuntimeError(f"enter failed: {self.name}")
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Record exit."""
        self.events.append(f"exit:{self.name}")


def _binding(
    key_name: str,
    toolkit: _TrackingToolkit,
    *,
    slug: str | None = None,
    use_prefix: bool = False,
    toolkit_type: str | None = None,
) -> SessionToolkitBinding:
    """Create a keyed test binding."""
    return SessionToolkitBinding(
        key=SessionToolkitKey(namespace="test", name=key_name),
        binding=ToolkitBinding(
            toolkit=toolkit,
            slug=slug if slug is not None else key_name,
            use_prefix=use_prefix,
            toolkit_type=toolkit_type,
        ),
    )


@pytest.mark.asyncio
async def test_reconcile_enters_toolkits_before_returning_snapshot() -> None:
    """New toolkit bindings are entered before being returned."""
    events: list[str] = []
    lifecycle = SessionToolkitLifecycle()
    toolkit = _TrackingToolkit("a", events)

    result = await lifecycle.reconcile([_binding("a", toolkit)])

    try:
        assert result[0].toolkit is toolkit
        assert events == ["enter:a"]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_reconcile_reuses_existing_toolkit_for_same_key() -> None:
    """Same key keeps the entered toolkit instance and refreshes metadata."""
    events: list[str] = []
    lifecycle = SessionToolkitLifecycle()
    first = _TrackingToolkit("first", events)
    replacement = _TrackingToolkit("replacement", events)

    first_result = await lifecycle.reconcile([_binding("same", first)])
    second_result = await lifecycle.reconcile(
        [
            _binding(
                "same",
                replacement,
                slug="renamed",
                use_prefix=True,
                toolkit_type="mcp",
            )
        ]
    )

    try:
        assert first_result[0].toolkit is first
        assert second_result[0].toolkit is first
        assert second_result[0].slug == "renamed"
        assert second_result[0].use_prefix is True
        assert second_result[0].toolkit_type == "mcp"
        assert events == ["enter:first"]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_reconcile_exits_removed_toolkits_after_success() -> None:
    """Removed toolkit bindings are exited after a successful reconcile."""
    events: list[str] = []
    lifecycle = SessionToolkitLifecycle()
    first = _TrackingToolkit("first", events)
    second = _TrackingToolkit("second", events)

    await lifecycle.reconcile([_binding("first", first), _binding("second", second)])
    result = await lifecycle.reconcile(
        [_binding("first", _TrackingToolkit("new", events))]
    )

    try:
        assert result[0].toolkit is first
        assert events == ["enter:first", "enter:second", "exit:second"]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_reconcile_unwinds_new_toolkits_when_later_enter_fails() -> None:
    """Failed reconcile unwinds newly entered toolkits and keeps old entries active."""
    events: list[str] = []
    lifecycle = SessionToolkitLifecycle()
    existing = _TrackingToolkit("existing", events)
    new_toolkit = _TrackingToolkit("new", events)
    failing = _TrackingToolkit("failing", events, fail_enter=True)

    await lifecycle.reconcile([_binding("existing", existing)])

    with pytest.raises(RuntimeError, match="enter failed: failing"):
        await lifecycle.reconcile(
            [
                _binding("existing", _TrackingToolkit("ignored", events)),
                _binding("new", new_toolkit),
                _binding("failing", failing),
            ]
        )

    result = await lifecycle.reconcile(
        [_binding("existing", _TrackingToolkit("again", events))]
    )

    try:
        assert result[0].toolkit is existing
        assert events == [
            "enter:existing",
            "enter:new",
            "enter:failing",
            "exit:new",
        ]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_close_exits_active_toolkits_once_in_reverse_order() -> None:
    """close exits active toolkit contexts once in reverse active order."""
    events: list[str] = []
    lifecycle = SessionToolkitLifecycle()

    await lifecycle.reconcile(
        [
            _binding("first", _TrackingToolkit("first", events)),
            _binding("second", _TrackingToolkit("second", events)),
        ]
    )

    await lifecycle.close()
    await lifecycle.close()

    assert events == [
        "enter:first",
        "enter:second",
        "exit:second",
        "exit:first",
    ]


@pytest.mark.asyncio
async def test_reconcile_rejects_duplicate_keys_before_side_effects() -> None:
    """Duplicate keys are rejected before entering any toolkit."""
    events: list[str] = []
    lifecycle = SessionToolkitLifecycle()

    with pytest.raises(DuplicateSessionToolkitKeyError, match="test:dup"):
        await lifecycle.reconcile(
            [
                _binding("dup", _TrackingToolkit("first", events)),
                _binding("dup", _TrackingToolkit("second", events)),
            ]
        )

    try:
        assert events == []
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_reconcile_after_close_raises_lifecycle_error() -> None:
    """Closed lifecycle cannot be reused."""
    lifecycle = SessionToolkitLifecycle()

    await lifecycle.close()

    with pytest.raises(SessionToolkitLifecycleClosedError):
        await lifecycle.reconcile([])
