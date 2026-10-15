"""Owned Browser logical-stream consumer with volatile latest-page frames."""

import asyncio
import contextlib
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, assert_never

from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAction,
    BrowserTarget,
)
from azents_runtime_control.browser_viewer_contract import (
    MAX_VIEWER_HEADER_BYTES,
    MAX_VIEWER_MESSAGE_BYTES,
    BrowserViewerContractError,
    ViewerComposition,
    ViewerDialog,
    ViewerDialogResponse,
    ViewerFrame,
    ViewerFrameAck,
    ViewerInput,
    ViewerInputAck,
    ViewerInputReason,
    ViewerKey,
    ViewerNavigation,
    ViewerPointer,
    ViewerSource,
    ViewerStatus,
    ViewerTarget,
    ViewerWheel,
    decode_viewer_request,
    encode_viewer_event,
    encode_viewer_frame,
)
from azents_runtime_control.runtime_stream_session import (
    BrowserStreamAuthority,
    WebSocketOpcode,
)
from playwright.async_api import Error, Page

from azents_runtime_runner.browser import (
    _CREDENTIAL_FIELDS,
    BrowserFailure,
    RunnerBrowserManager,
    _ActionOutcome,
    _Page,
    _safe_page_text,
    _Task,
)


class BrowserFrameBudget(Protocol):
    """Use the same process application-byte ceiling as transport envelopes."""

    def try_reserve_browser_frame(self, size: int) -> bool: ...
    def release_browser_frame(self, size: int) -> None: ...


type ViewerSend = Callable[[WebSocketOpcode, bytes], Awaitable[None]]
type ViewerReceive = Callable[[], Awaitable[bytes | None]]


@dataclass(frozen=True)
class _Image:
    source: ViewerSource
    data: bytes


class _LatestPage:
    def __init__(self, page: _Page, budget: BrowserFrameBudget) -> None:
        self.page = page
        self.budget = budget
        self.latest: _Image | None = None
        self.sequence = 0
        self.subscribers = 0
        self.failed = False
        self.changed = asyncio.Condition()
        self.task: asyncio.Task[None] | None = None

    async def capture(self) -> None:
        try:
            while not self.page.page.is_closed():
                if self.page.dialog is None:
                    await self.capture_once()
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except Error, BrowserFailure:
            self.failed = True
        finally:
            async with self.changed:
                self.changed.notify_all()

    async def capture_once(self) -> None:
        navigation = self.page.navigation_id
        viewport = _viewport(self.page.page)
        scratch = viewport[0] * viewport[1] * 4 + MAX_VIEWER_MESSAGE_BYTES
        if not self.budget.try_reserve_browser_frame(scratch):
            raise BrowserFailure(
                "browser_resource_exhausted", "Browser capture budget is exhausted"
            )
        try:
            data = await self.screenshot(navigation)
            if data is None:
                return
            if navigation != self.page.navigation_id or viewport != _viewport(
                self.page.page
            ):
                return
            if len(data) + MAX_VIEWER_HEADER_BYTES + 4 > MAX_VIEWER_MESSAGE_BYTES:
                raise BrowserFailure(
                    "browser_frame_oversized", "Browser live frame exceeds its bound"
                )
            async with self.changed:
                self.clear()
                if not self.budget.try_reserve_browser_frame(len(data)):
                    raise BrowserFailure(
                        "browser_resource_exhausted",
                        "Browser live frame budget is exhausted",
                    )
                self.sequence += 1
                self.latest = _Image(
                    ViewerSource(self.sequence, navigation, viewport[0], viewport[1]),
                    data,
                )
                self.changed.notify_all()
        finally:
            self.budget.release_browser_frame(scratch)

    async def screenshot(self, navigation: str) -> bytes | None:
        try:
            return await self.page.page.screenshot(
                type="jpeg",
                scale="css",
                quality=60,
                full_page=False,
                timeout=2000,
                mask=[
                    frame.locator(_CREDENTIAL_FIELDS)
                    for frame in self.page.page.frames
                    if not frame.is_detached()
                ],
                mask_color="#000000",
            )
        except Error:
            if (
                self.page.dialog is not None
                or navigation != self.page.navigation_id
                or self.page.page.is_closed()
            ):
                return None
            raise

    def clear(self) -> None:
        if self.latest is not None:
            self.budget.release_browser_frame(len(self.latest.data))
            self.latest = None

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.clear()


def _viewport(page: Page) -> tuple[int, int]:
    viewport = page.viewport_size
    if viewport is None:
        raise BrowserFailure(
            "browser_unavailable", "Browser source viewport is unavailable"
        )
    width, height = viewport["width"], viewport["height"]
    if (
        not 1 <= width <= 4096
        or not 1 <= height <= 4096
        or width * height > 8 * 1024 * 1024
    ):
        raise BrowserFailure(
            "browser_resource_exhausted", "Browser source viewport exceeds its bound"
        )
    return width, height


def _target(authority: BrowserStreamAuthority) -> BrowserTarget:
    return BrowserTarget(
        authority.task_id, authority.page_id, authority.resource_incarnation, None
    )


class RunnerBrowserViewer:
    """Bind admitted Browser authority directly to the existing manager."""

    def __init__(
        self, manager: RunnerBrowserManager, budget: BrowserFrameBudget
    ) -> None:
        self.manager = manager
        self.budget = budget
        self.sources: dict[str, _LatestPage] = {}

    def validate(self, authority: BrowserStreamAuthority) -> None:
        self.manager.viewer_authority(authority)

    async def run(
        self,
        authority: BrowserStreamAuthority,
        receive: ViewerReceive,
        send: ViewerSend,
    ) -> None:
        concrete = self.manager.viewer_authority(authority)
        task, page, _ = self.manager.target(concrete, _target(authority))
        source = self.sources.get(page.id)
        if source is None:
            source = _LatestPage(page, self.budget)
            self.sources[page.id] = source
            source.task = asyncio.create_task(
                source.capture(), name="browser-viewport-capture"
            )
        source.subscribers += 1
        attachment = _Attachment(self.manager, authority, task, page, source, send)
        readers: tuple[asyncio.Task[None], ...] = ()
        try:
            await attachment.status()
            readers = (
                asyncio.create_task(attachment.read(receive)),
                asyncio.create_task(attachment.write()),
            )
            done, pending = await asyncio.wait(
                readers, return_when=asyncio.FIRST_COMPLETED
            )
            for reader in pending:
                reader.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for reader in done:
                await reader
        finally:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            await attachment.cleanup()
            source.subscribers -= 1
            if source.subscribers == 0 and self.sources.get(page.id) is source:
                self.sources.pop(page.id, None)
                await source.close()

    async def close(self) -> None:
        for source in tuple(self.sources.values()):
            await source.close()
        self.sources.clear()


class _Attachment:
    def __init__(
        self,
        manager: RunnerBrowserManager,
        authority: BrowserStreamAuthority,
        task: _Task,
        page: _Page,
        source: _LatestPage,
        send: ViewerSend,
    ) -> None:
        self.manager = manager
        self.authority = authority
        self.task = task
        self.page = page
        self.source = source
        self.send = send
        self.id = uuid.uuid4().hex
        self.target = ViewerTarget(
            authority.task_id, authority.page_id, authority.resource_incarnation
        )
        self.sequence = 0
        self.sent: ViewerSource | None = None
        self.retired_frames: deque[int] = deque(maxlen=128)
        self.acknowledged: ViewerSource | None = None
        self.buttons: set[Literal["left", "middle", "right"]] = set()
        self.keys: set[str] = set()
        self.composing = False
        self.last_status: bytes | None = None
        self.send_lock = asyncio.Lock()

    def current(self) -> None:
        concrete = self.manager.viewer_authority(self.authority)
        task, page, _ = self.manager.target(concrete, _target(self.authority))
        if task is not self.task or page is not self.page:
            raise BrowserFailure(
                "browser_stale_target", "Browser viewer resource was replaced"
            )

    async def emit(self, opcode: WebSocketOpcode, data: bytes) -> None:
        async with self.send_lock:
            await self.send(opcode, data)

    async def status(self, state: str = "connected") -> None:
        width, height = _viewport(self.page.page)
        dialog = None
        if self.page.dialog is not None and self.page.dialog_id is not None:
            dialog = ViewerDialog(
                self.page.dialog_id,
                self.page.dialog.type,
                _safe_page_text(self.page.dialog.message)[:4096],
            )
        if state not in {"connected", "unavailable", "closed"}:
            raise BrowserViewerContractError("Invalid Browser viewer state")
        value = encode_viewer_event(
            ViewerStatus(
                self.id,
                self.target,
                state,
                self.authority.allow_input,
                width,
                height,
                self.page.navigation_id,
                dialog,
                self.task.guard.actor is not None and self.task.guard.actor != self.id,
            )
        )
        if value != self.last_status:
            await self.emit(WebSocketOpcode.TEXT, value)
            self.last_status = value

    async def write(self) -> None:
        while True:
            try:
                self.current()
            except BrowserFailure:
                await self.status("closed")
                return
            if self.source.failed:
                await self.status("unavailable")
                return
            await self.status()
            viewport = _viewport(self.page.page)
            if self.sent is not None and (
                self.sent.navigation_id != self.page.navigation_id
                or (self.sent.width, self.sent.height) != viewport
            ):
                self.retired_frames.append(self.sent.frame_sequence)
                self.sent = None
                self.acknowledged = None
            image = self.source.latest
            if (
                self.sent is None
                and image is not None
                and image.source.navigation_id == self.page.navigation_id
                and (image.source.width, image.source.height) == viewport
                and (
                    self.acknowledged is None
                    or image.source.frame_sequence > self.acknowledged.frame_sequence
                )
            ):
                reservation = len(image.data) + MAX_VIEWER_HEADER_BYTES + 4
                if not self.source.budget.try_reserve_browser_frame(reservation):
                    raise BrowserFailure(
                        "browser_resource_exhausted",
                        "Browser frame send budget is exhausted",
                    )
                self.sent = image.source
                try:
                    data = encode_viewer_frame(
                        ViewerFrame(self.id, self.target, image.source, image.data)
                    )
                    del image
                    await self.emit(WebSocketOpcode.BINARY, data)
                    del data
                finally:
                    self.source.budget.release_browser_frame(reservation)
            # Status stays responsive while an image waits for display acknowledgement.
            async with self.source.changed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.source.changed.wait(), 0.2)

    async def read(self, receive: ViewerReceive) -> None:
        while True:
            data = await receive()
            if data is None:
                return
            request = decode_viewer_request(data)
            if request.attachment_id != self.id:
                raise BrowserViewerContractError(
                    "Browser attachment is no longer current"
                )
            self.current()
            match request:
                case ViewerFrameAck():
                    if request.frame_sequence in self.retired_frames:
                        continue
                    if (
                        self.sent is None
                        or request.frame_sequence != self.sent.frame_sequence
                    ):
                        raise BrowserViewerContractError(
                            "Browser frame acknowledgement is stale"
                        )
                    self.acknowledged, self.sent = self.sent, None
                    async with self.source.changed:
                        self.source.changed.notify_all()
                case ViewerInput():
                    await self.input(request)
                case _:
                    assert_never(request)

    async def input(self, request: ViewerInput) -> None:
        accepted = False
        reason: ViewerInputReason | None = None
        outcome = "rejected"
        try:
            if not self.authority.allow_input:
                raise BrowserFailure(
                    "browser_read_only", "Browser attachment is observation-only"
                )
            if request.sequence <= self.sequence:
                raise BrowserFailure(
                    "browser_stale_input", "Browser input sequence is stale"
                )
            self.sequence = request.sequence
            self.current()
            if not isinstance(request.action, ViewerDialogResponse):
                acknowledged = self.acknowledged
                if (
                    acknowledged is None
                    or request.source != acknowledged
                    or acknowledged.navigation_id != self.page.navigation_id
                    or (acknowledged.width, acknowledged.height)
                    != _viewport(self.page.page)
                ):
                    raise BrowserFailure(
                        "browser_stale_frame",
                        "Browser source frame is no longer current",
                    )
            await self.dispatch(request)
            accepted, outcome = True, "dispatched"
        except BrowserFailure as error:
            try:
                reason = ViewerInputReason(error.code)
            except ValueError:
                reason = ViewerInputReason.OUTCOME_UNKNOWN
            if reason in {
                ViewerInputReason.STALE_FRAME,
                ViewerInputReason.STALE_TARGET,
                ViewerInputReason.STALE_GENERATION,
            }:
                await self.cleanup()
        except Error:
            reason, outcome = ViewerInputReason.OUTCOME_UNKNOWN, "outcome_unknown"
            await self.cleanup()
        ack = ViewerInputAck(self.id, request.sequence, accepted, reason, outcome)
        await self.emit(WebSocketOpcode.TEXT, encode_viewer_event(ack))
        await self.status()

    def begin(self) -> None:
        if self.task.guard.actor != self.id:
            self.task.guard.begin(self.id)

    def finish(self) -> None:
        if (
            not self.buttons
            and not self.keys
            and not self.composing
            and self.task.guard.actor == self.id
        ):
            self.task.guard.end(self.id)

    def coordinate(self, x: float, y: float) -> None:
        width, height = _viewport(self.page.page)
        if not 0 <= x < width or not 0 <= y < height:
            raise BrowserFailure(
                "browser_stale_frame",
                "Browser coordinates are outside the source viewport",
            )

    async def effect(self, call: Callable[[], Awaitable[None]]) -> None:
        if self.page.dialog is not None or self.page.pending is not None:
            raise BrowserFailure(
                "browser_dialog_pending",
                "Resolve the current page dialog before another input",
            )

        async def run() -> _ActionOutcome:
            self.current()
            source = self.acknowledged
            if (
                source is None
                or source.navigation_id != self.page.navigation_id
                or (source.width, source.height) != _viewport(self.page.page)
            ):
                raise BrowserFailure(
                    "browser_stale_frame",
                    "Browser source changed before input dispatch",
                )
            await call()
            return _ActionOutcome(None, None)

        pending = asyncio.create_task(run())
        self.page.pending = pending
        await self.manager._await_dispatch_or_dialog(self.page, pending)
        if self.page.dialog is not None:
            # The page is waiting for a dialog, not issuing further input.
            await self.cleanup()

    async def dispatch(self, request: ViewerInput) -> None:
        action = request.action
        if isinstance(action, ViewerNavigation):
            if self.buttons or self.keys or self.composing:
                raise BrowserFailure(
                    "browser_input_conflict",
                    "Finish the current Browser interaction before navigation",
                )
            concrete = self.manager.viewer_authority(self.authority)
            await self.manager.execute(
                BrowserActCommand(
                    concrete,
                    _target(self.authority),
                    BrowserAction(
                        kind=action.action,
                        ref=None,
                        observation_id=None,
                        text=None,
                        url=action.url,
                        values=None,
                        checked=None,
                        key=None,
                        x=None,
                        y=None,
                        end_ref=None,
                        paths=None,
                        dialog_id=None,
                        accept=None,
                        condition=None,
                        expect=None,
                        timeout_ms=10000,
                    ),
                )
            )
            await self.cleanup()
            return
        if isinstance(action, ViewerDialogResponse):
            concrete = self.manager.viewer_authority(self.authority)
            command = BrowserAction(
                "dialog",
                None,
                None,
                action.text,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                action.dialog_id,
                action.accept,
                None,
                None,
                30000,
            )
            await self.manager.execute(
                BrowserActCommand(concrete, _target(self.authority), command)
            )
            if self.page.dialog is None:
                await self.cleanup()
            return
        if self.page.dialog is not None or self.page.pending is not None:
            raise BrowserFailure(
                "browser_dialog_pending",
                "Resolve the current page dialog before another input",
            )
        self.begin()
        try:
            self.current()
            match action:
                case ViewerPointer():
                    if action.phase != "cancel":
                        self.coordinate(action.x, action.y)
                    if action.phase == "move":
                        await self.effect(
                            lambda: self.page.page.mouse.move(action.x, action.y)
                        )
                    elif action.phase == "down":
                        if action.button is None or action.button in self.buttons:
                            raise BrowserFailure(
                                "browser_stale_input",
                                "Browser pointer is already pressed",
                            )
                        self.buttons.add(action.button)
                        await self.effect(
                            lambda: self.page.page.mouse.move(action.x, action.y)
                        )
                        await self.effect(
                            lambda: self.page.page.mouse.down(button=action.button)
                        )
                    elif action.phase == "up":
                        if action.button not in self.buttons:
                            raise BrowserFailure(
                                "browser_stale_input", "Browser pointer is not pressed"
                            )
                        await self.effect(
                            lambda: self.page.page.mouse.move(action.x, action.y)
                        )
                        self.buttons.discard(action.button)
                        await self.effect(
                            lambda: self.page.page.mouse.up(button=action.button)
                        )
                    else:
                        await self.cleanup()
                case ViewerWheel():
                    self.coordinate(action.x, action.y)
                    await self.effect(
                        lambda: self.page.page.mouse.move(action.x, action.y)
                    )
                    await self.effect(
                        lambda: self.page.page.mouse.wheel(
                            action.delta_x, action.delta_y
                        )
                    )
                case ViewerKey():
                    if self.composing:
                        raise BrowserFailure(
                            "browser_input_conflict", "Browser composition is active"
                        )
                    if action.phase == "down":
                        if len(self.keys) >= 8 and action.key not in self.keys:
                            raise BrowserFailure(
                                "browser_resource_exhausted",
                                "Browser held key bound exceeded",
                            )
                        self.keys.add(action.key)
                        await self.effect(
                            lambda: self.page.page.keyboard.down(action.key)
                        )
                    else:
                        if action.key not in self.keys:
                            raise BrowserFailure(
                                "browser_stale_input", "Browser key is not pressed"
                            )
                        self.keys.discard(action.key)
                        await self.effect(
                            lambda: self.page.page.keyboard.up(action.key)
                        )
                case ViewerComposition():
                    if action.phase == "start":
                        if self.composing or self.buttons or self.keys:
                            raise BrowserFailure(
                                "browser_input_conflict",
                                "Another Browser interaction is active",
                            )
                        self.composing = True
                    elif not self.composing:
                        raise BrowserFailure(
                            "browser_stale_input", "Browser composition is not active"
                        )
                    elif action.phase == "commit":
                        assert action.text is not None
                        text = action.text
                        self.composing = False
                        await self.effect(
                            lambda: self.page.page.keyboard.insert_text(text)
                        )
                    else:
                        self.composing = False
                case _:
                    assert_never(action)
        finally:
            self.finish()

    async def cleanup(self) -> None:
        # Never release another attachment's pressed state or guard.
        owns = self.task.guard.actor == self.id or self.task.guard.actor is None
        try:
            if owns and not self.page.page.is_closed():
                async with asyncio.timeout(2):
                    for button in tuple(self.buttons):
                        await self.page.page.mouse.up(button=button)
                    for key in tuple(self.keys):
                        await self.page.page.keyboard.up(key)
        except Error, TimeoutError:
            logging.getLogger(__name__).info(
                "Browser attachment cleanup outcome is unconfirmed",
                extra={"reason_code": "browser_outcome_unknown"},
            )
        finally:
            self.buttons.clear()
            self.keys.clear()
            self.composing = False
            if self.task.guard.actor == self.id:
                self.task.guard.end(self.id)
