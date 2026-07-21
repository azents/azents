"""Session-scoped toolkit lifecycle management."""

import dataclasses
from collections.abc import Sequence
from contextlib import AsyncExitStack

from azents.engine.run.contracts import ToolkitBinding


class DuplicateSessionToolkitKeyError(ValueError):
    """A reconcile request contained the same session toolkit key twice."""


class SessionToolkitLifecycleClosedError(RuntimeError):
    """The session toolkit lifecycle has already been closed."""


@dataclasses.dataclass(frozen=True, slots=True)
class SessionToolkitKey:
    """Stable key for a toolkit instance within one AgentSession."""

    namespace: str
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class SessionToolkitBinding:
    """A desired toolkit binding plus its session-stable identity."""

    key: SessionToolkitKey
    binding: ToolkitBinding


@dataclasses.dataclass(slots=True)
class _EnteredToolkit:
    """Toolkit instance currently owned by the session lifecycle."""

    key: SessionToolkitKey
    binding: ToolkitBinding
    stack: AsyncExitStack

    async def close(self) -> None:
        """Exit the managed toolkit context."""
        await self.stack.aclose()


class SessionToolkitLifecycle:
    """Owns entered toolkit instances for one active AgentSession."""

    def __init__(self) -> None:
        self._entries: dict[SessionToolkitKey, _EnteredToolkit] = {}
        self._closed = False

    async def reconcile(
        self,
        desired: Sequence[SessionToolkitBinding],
    ) -> list[ToolkitBinding]:
        """Reconcile active toolkit instances to the desired ordered snapshot."""
        if self._closed:
            raise SessionToolkitLifecycleClosedError

        _ensure_unique_keys(desired)

        desired_keys = {item.key for item in desired}
        result: list[ToolkitBinding] = []
        new_entries: dict[SessionToolkitKey, _EnteredToolkit] = {}
        refresh_entries: list[tuple[_EnteredToolkit, ToolkitBinding]] = []

        async with AsyncExitStack() as rollback_stack:
            for item in desired:
                existing = self._entries.get(item.key)
                if existing is not None:
                    refresh_entries.append(
                        (
                            existing,
                            item.binding,
                        )
                    )
                    binding = item.binding._replace(toolkit=existing.binding.toolkit)
                    existing.binding = binding
                    result.append(binding)
                    continue

                entry = await _enter_binding(item)
                new_entries[item.key] = entry
                result.append(entry.binding)
                rollback_stack.push_async_callback(entry.close)

            for entry, refreshed_binding in refresh_entries:
                await entry.binding.toolkit.refresh_from_resolved(
                    refreshed_binding.toolkit
                )

            rollback_stack.pop_all()

        removed = [
            entry for key, entry in self._entries.items() if key not in desired_keys
        ]
        await _close_entries(removed)

        updated: dict[SessionToolkitKey, _EnteredToolkit] = {}
        for item, binding in zip(desired, result, strict=True):
            entry = self._entries.get(item.key) or new_entries[item.key]
            entry.binding = binding
            updated[item.key] = entry
        self._entries = updated

        return result

    async def close(self) -> None:
        """Exit all active toolkit instances once."""
        if self._closed:
            return
        self._closed = True
        entries = list(self._entries.values())
        self._entries = {}
        await _close_entries(entries)


def _ensure_unique_keys(desired: Sequence[SessionToolkitBinding]) -> None:
    """Reject duplicate desired toolkit keys before side effects."""
    seen: set[SessionToolkitKey] = set()
    duplicates: list[SessionToolkitKey] = []
    for item in desired:
        if item.key in seen:
            duplicates.append(item.key)
        seen.add(item.key)
    if duplicates:
        formatted = ", ".join(f"{key.namespace}:{key.name}" for key in duplicates)
        raise DuplicateSessionToolkitKeyError(formatted)


async def _enter_binding(item: SessionToolkitBinding) -> _EnteredToolkit:
    """Enter one desired binding and return the managed entry."""
    stack = AsyncExitStack()
    toolkit = await stack.enter_async_context(item.binding.toolkit)
    binding = item.binding._replace(toolkit=toolkit)
    return _EnteredToolkit(key=item.key, binding=binding, stack=stack)


async def _close_entries(entries: Sequence[_EnteredToolkit]) -> None:
    """Close entries in reverse order using one structured exit stack."""
    async with AsyncExitStack() as stack:
        for entry in entries:
            stack.push_async_callback(entry.close)
