"""Correlate native popup creation with an actual managed pointer operation."""

from collections.abc import Callable
from dataclasses import dataclass

from patchright.async_api import CDPSession, Error, Page


@dataclass(frozen=True)
class _NativeTarget:
    id: str
    opener: str | None


@dataclass(eq=False)
class _PopupOwner:
    target_id: str
    owner: str
    valid: bool


def _target(value: object) -> _NativeTarget:
    if not isinstance(value, dict):
        raise ValueError("Invalid native Browser target metadata")
    identifier, opener = value.get("targetId"), value.get("openerId")
    if (
        not isinstance(identifier, str)
        or not identifier
        or (opener is not None and not isinstance(opener, str))
    ):
        raise ValueError("Invalid native Browser target identity")
    return _NativeTarget(identifier, opener)


async def _page_target(session: CDPSession) -> _NativeTarget:
    result = await session.send("Target.getTargetInfo")
    return _target(result["targetInfo"])


async def _detach(session: CDPSession, page: Page) -> None:
    try:
        await session.detach()
    except Error:
        if not page.is_closed():
            raise


class BrowserPopupTracker:
    """Use only content-free Chromium target IDs; never expose the native session."""

    def __init__(self, page: Page, owner: Callable[[], str | None]) -> None:
        self.page = page
        self.owner = owner
        self.session: CDPSession | None = None
        self.target_id: str | None = None
        self.pending: dict[str, _PopupOwner] = {}
        self.consuming: list[_PopupOwner] = []

    async def start(self) -> None:
        if self.session is not None:
            return
        self.session = await self.page.context.new_cdp_session(self.page)
        self.target_id = (await _page_target(self.session)).id
        self.session.on("Target.targetCreated", self.created)
        self.session.on("Target.targetDestroyed", self.destroyed)
        await self.session.send("Target.setDiscoverTargets", {"discover": True})

    def created(self, event: object) -> None:
        if not isinstance(event, dict):
            raise ValueError("Invalid native Browser popup event")
        target = _target(event.get("targetInfo"))
        owner = self.owner()
        if (
            target.opener == self.target_id
            and owner is not None
            and len(self.pending) + len(self.consuming) < 16
        ):
            self.pending[target.id] = _PopupOwner(target.id, owner, True)

    async def consume(self, page: Page) -> str | None:
        if page.context != self.page.context:
            raise ValueError("Browser popup context changed")
        if not self.pending:
            return None
        try:
            session = await page.context.new_cdp_session(page)
        except Error:
            if not page.is_closed():
                raise
            return None
        record = None
        try:
            identifier = (await _page_target(session)).id
            record = self.pending.pop(identifier, None)
            if record is not None:
                self.consuming.append(record)
        except Error:
            if not page.is_closed():
                raise
            return None
        finally:
            try:
                await _detach(session, page)
            finally:
                if record is not None:
                    self.consuming.remove(record)
        return (
            record.owner
            if record is not None and record.valid and not page.is_closed()
            else None
        )

    def clear(self) -> None:
        for record in (*self.pending.values(), *self.consuming):
            record.valid = False
        self.pending.clear()

    def destroyed(self, event: object) -> None:
        if not isinstance(event, dict) or not isinstance(event.get("targetId"), str):
            raise ValueError("Invalid native Browser target destruction")
        self.pending.pop(event["targetId"], None)
        for record in self.consuming:
            if record.target_id == event["targetId"]:
                record.valid = False

    def discard(self, owner: str) -> None:
        for record in (*self.pending.values(), *self.consuming):
            if record.owner == owner:
                record.valid = False
        self.pending = {
            key: value for key, value in self.pending.items() if value.owner != owner
        }

    async def close(self) -> None:
        self.clear()
        if self.session is not None:
            self.session.remove_listener("Target.targetCreated", self.created)
            self.session.remove_listener("Target.targetDestroyed", self.destroyed)
            await _detach(self.session, self.page)
            self.session = None
