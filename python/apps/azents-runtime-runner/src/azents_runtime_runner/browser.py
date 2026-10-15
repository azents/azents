"""Runner-owned browser resources and task-local structured SDK execution."""

import asyncio
import hashlib
import mimetypes
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, assert_never
from urllib.parse import urlsplit, urlunsplit

from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAction,
    BrowserAuthority,
    BrowserCapture,
    BrowserCommand,
    BrowserDialog,
    BrowserElementRef,
    BrowserFrame,
    BrowserObserveCommand,
    BrowserOpenCommand,
    BrowserPage,
    BrowserResult,
    BrowserTarget,
    BrowserTask,
)
from azents_runtime_control.browser_viewer_contract import ViewerTarget
from azents_runtime_control.runtime_stream_session import BrowserStreamAuthority
from markdownify import markdownify
from playwright.async_api import (
    BrowserContext,
    Dialog,
    Download,
    ElementHandle,
    Error,
    Frame,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from azents_runtime_runner.browser_popups import BrowserPopupTracker

_MAX_TASKS = 64
_MAX_PAGES = 8
_MAX_SESSION_TASKS = 8
_MAX_FRAMES = 16
_MAX_REFS = 1000
_MAX_CAPTURE_BYTES = 20 * 1024 * 1024


class BrowserFailure(RuntimeError):
    """Content-free browser failure with a stable Runtime error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def safe_browser_url(url: str) -> str:
    """Project source URL without user information, query or fragment."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https", "about"}:
        return parts.scheme + ":" if parts.scheme else "about:blank"
    host = parts.hostname or ""
    if parts.port is not None:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))[:256]


def _url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise BrowserFailure(
            "browser_invalid_url",
            "Browser navigation requires an HTTP(S) URL without credentials",
        )
    return url


class BrowserInteractionGuard:
    """Actual manipulation arbitration; never a persistent human-control mode."""

    def __init__(self) -> None:
        self.actor: str | None = None

    def begin(self, actor: str) -> None:
        if self.actor is not None:
            raise BrowserFailure(
                "browser_input_conflict",
                "Another input interaction is active for this task",
            )
        self.actor = actor

    def end(self, actor: str) -> None:
        if self.actor != actor:
            raise BrowserFailure(
                "browser_stale_input", "Browser input interaction is no longer current"
            )
        self.actor = None

    @asynccontextmanager
    async def interaction(self, actor: str) -> AsyncIterator[None]:
        self.begin(actor)
        try:
            yield
        finally:
            if self.actor == actor:
                self.end(actor)


@dataclass
class _Reference:
    handle: ElementHandle
    observation_id: str
    frame: Frame


@dataclass(frozen=True)
class _ActionOutcome:
    popup: BrowserPage | None
    download: BrowserCapture | None


@dataclass(frozen=True)
class _PopupSelection:
    owner: str
    target: ViewerTarget


@dataclass
class _Page:
    id: str
    page: Page
    popup_owner: str | None
    popup_selection: _PopupSelection | None
    popup_tracker: BrowserPopupTracker | None
    frames: dict[str, Frame] = field(default_factory=dict)
    refs: dict[str, _Reference] = field(default_factory=dict)
    dialog: Dialog | None = None
    dialog_id: str | None = None
    dialog_ready: asyncio.Event = field(default_factory=asyncio.Event)
    pending: asyncio.Task[_ActionOutcome] | None = None
    navigation_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class _Task:
    id: str
    session_id: str
    label: str
    incarnation: str
    working_directory: Path
    pages: dict[str, _Page] = field(default_factory=dict)
    guard: BrowserInteractionGuard = field(default_factory=BrowserInteractionGuard)


class RunnerBrowserManager:
    """Own product browser contexts, identities and every supported input path."""

    def __init__(self, *, workspace_root: Path, proxy: str | None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.proxy = proxy
        self.driver: Playwright | None = None
        self.contexts: dict[str, BrowserContext] = {}
        self.tasks: dict[str, _Task] = {}
        self.session_directories: dict[str, Path] = {}
        self.sandbox: bool | None = None
        self.start_lock = asyncio.Lock()
        self.session_locks: dict[str, asyncio.Lock] = {}
        self.closed = False
        self.runtime_id: str | None = None
        self.generation: Callable[[], int | None] | None = None

    def bind_runtime(
        self, runtime_id: str, generation: Callable[[], int | None]
    ) -> None:
        """Bind one manager to its current Runner connection generation."""
        if self.runtime_id is not None:
            raise ValueError("Browser manager Runtime is already bound")
        self.runtime_id = runtime_id
        self.generation = generation

    def validate_operation(self, runtime_id: str, generation: int) -> None:
        """Fence command transport immediately before registry/effect access."""
        if (
            self.runtime_id != runtime_id
            or self.generation is None
            or self.generation() != generation
        ):
            raise BrowserFailure(
                "browser_stale_generation",
                "Browser Runtime generation is no longer current",
            )

    def viewer_authority(self, authority: BrowserStreamAuthority) -> BrowserAuthority:
        """Resolve only an existing Session binding; attachment never creates state."""
        self.validate_operation(authority.runtime_id, authority.runner_generation)
        task = self.tasks.get(authority.task_id)
        if self.closed or task is None or task.session_id != authority.session_id:
            raise BrowserFailure(
                "browser_stale_target", "Browser viewer target is unavailable"
            )
        bound = self.session_directories.get(authority.session_id)
        if bound is None or bound != task.working_directory:
            raise BrowserFailure(
                "browser_invalid_authority", "Browser Session binding is unavailable"
            )
        concrete = BrowserAuthority(task.session_id, str(bound))
        self.target(
            concrete,
            BrowserTarget(
                authority.task_id,
                authority.page_id,
                authority.resource_incarnation,
                None,
            ),
        )
        return concrete

    async def initialize(self) -> None:
        """Establish product engine availability without opening a Session page."""
        try:
            await self._initialize()
        except Error:
            raise BrowserFailure(
                "browser_unavailable", "Product browser initialization failed"
            ) from None

    def _authority(self, authority: BrowserAuthority) -> Path:
        if self.closed:
            raise BrowserFailure("browser_unavailable", "Browser manager is closed")
        directory = Path(authority.working_directory)
        if not directory.is_absolute():
            raise BrowserFailure(
                "browser_invalid_authority",
                "Browser working directory must be absolute",
            )
        resolved = directory.resolve()
        if not resolved.is_relative_to(self.workspace_root):
            raise BrowserFailure(
                "browser_invalid_authority",
                "Browser working directory is outside the reported Workspace",
            )
        previous = self.session_directories.get(authority.session_id)
        if previous is not None and previous != resolved:
            raise BrowserFailure(
                "browser_invalid_authority", "Browser Session working directory changed"
            )
        resolved.mkdir(parents=True, exist_ok=True)
        self.session_directories[authority.session_id] = resolved
        return resolved

    async def _initialize(self) -> Playwright:
        async with self.start_lock:
            if self.driver is not None:
                return self.driver
            driver = await async_playwright().start()
            try:
                probe = await driver.chromium.launch(
                    headless=True, chromium_sandbox=True
                )
                await probe.close()
                self.sandbox = True
            except Error as exc:
                # Only known native containment startup diagnostics permit downgrade.
                if not _sandbox_unavailable(str(exc)):
                    await driver.stop()
                    raise BrowserFailure(
                        "browser_unavailable", "Product browser startup failed"
                    ) from None
                self.sandbox = False
                try:
                    probe = await driver.chromium.launch(
                        headless=True, chromium_sandbox=False
                    )
                    await probe.close()
                except Error:
                    await driver.stop()
                    raise BrowserFailure(
                        "browser_unavailable", "Product browser startup failed"
                    ) from None
            self.driver = driver
            return driver

    async def _context(self, authority: BrowserAuthority) -> BrowserContext:
        lock = self.session_locks.setdefault(authority.session_id, asyncio.Lock())
        async with lock:
            existing = self.contexts.get(authority.session_id)
            if existing is not None:
                return existing
            driver = await self._initialize()
            token = hashlib.sha256(authority.session_id.encode()).hexdigest()
            path = self.workspace_root / ".azents" / "browser-state" / token
            if path.resolve() != path or path.is_symlink():
                raise BrowserFailure(
                    "browser_invalid_authority", "Native browser state path is invalid"
                )
            path.mkdir(parents=True, exist_ok=True)
            try:
                context = await driver.chromium.launch_persistent_context(
                    path,
                    headless=True,
                    chromium_sandbox=self.sandbox is True,
                    proxy=None
                    if self.proxy is None
                    else {"server": self.proxy, "bypass": "<-loopback>"},
                    viewport={"width": 1280, "height": 800},
                    accept_downloads=True,
                )
            except Error:
                raise BrowserFailure(
                    "browser_unavailable", "Product browser context could not start"
                ) from None
            for initial in context.pages:
                await initial.close()
            self.contexts[authority.session_id] = context
            return context

    def _task(self, authority: BrowserAuthority, task_id: str) -> _Task:
        task = self.tasks.get(task_id)
        if task is None or task.session_id != authority.session_id:
            raise BrowserFailure(
                "browser_stale_target", "Browser task is closed or not authorized"
            )
        return task

    def target(
        self, authority: BrowserAuthority, target: BrowserTarget
    ) -> tuple[_Task, _Page, Frame]:
        """Resolve final live identity for commands and later admitted viewer input."""
        self._authority(authority)
        task = self._task(authority, target.task_id)
        page = task.pages.get(target.page_id)
        if (
            task.incarnation != target.resource_incarnation
            or page is None
            or page.page.is_closed()
        ):
            raise BrowserFailure(
                "browser_stale_target", "Browser page identity is no longer current"
            )
        frame = (
            page.page.main_frame
            if target.frame_id is None
            else page.frames.get(target.frame_id)
        )
        if frame is None or frame.is_detached():
            raise BrowserFailure(
                "browser_stale_target", "Browser frame is no longer current"
            )
        return task, page, frame

    def _register(self, task: _Task, page: Page) -> _Page:
        if self.tasks.get(task.id) is not task or page.is_closed():
            raise BrowserFailure(
                "browser_stale_target", "Browser task or page is no longer current"
            )
        for existing in task.pages.values():
            if existing.page == page:
                return existing
        if len(task.pages) >= _MAX_PAGES:
            raise BrowserFailure(
                "browser_resource_exhausted", "Browser task page limit reached"
            )
        resource = _Page(uuid.uuid4().hex, page, None, None, None)
        task.pages[resource.id] = resource
        for frame in page.frames[:_MAX_FRAMES]:
            resource.frames[uuid.uuid4().hex] = frame

        def attached(frame: Frame) -> None:
            if len(resource.frames) < _MAX_FRAMES:
                resource.frames[uuid.uuid4().hex] = frame

        def detached(frame: Frame) -> None:
            resource.frames = {
                key: value for key, value in resource.frames.items() if value != frame
            }
            resource.refs = {
                key: value
                for key, value in resource.refs.items()
                if value.frame != frame
            }

        def navigated(frame: Frame) -> None:
            if frame == page.main_frame:
                resource.navigation_id = uuid.uuid4().hex
                resource.popup_owner = None
                resource.popup_selection = None
                if resource.popup_tracker is not None:
                    resource.popup_tracker.clear()
            resource.refs = {
                key: value
                for key, value in resource.refs.items()
                if value.frame != frame
            }

        def dialog(value: Dialog) -> None:
            resource.dialog = value
            resource.dialog_id = uuid.uuid4().hex
            resource.dialog_ready.set()

        page.on("frameattached", attached)
        page.on("framedetached", detached)
        page.on("framenavigated", navigated)
        page.on("dialog", dialog)

        async def popup(value: Page) -> None:
            if value.is_closed():
                return
            if self.tasks.get(task.id) is not task or len(task.pages) >= _MAX_PAGES:
                await value.close()
                return
            opened = self._register(task, value)
            owner = (
                await resource.popup_tracker.consume(value)
                if resource.popup_tracker is not None
                else None
            )
            if owner is not None:
                resource.popup_selection = _PopupSelection(
                    owner,
                    ViewerTarget(task.id, opened.id, task.incarnation),
                )

        def closed(value: Page) -> None:
            del value
            if resource.pending is not None:
                resource.pending.cancel()
            task.pages.pop(resource.id, None)
            if not task.pages:
                self.tasks.pop(task.id, None)

        page.on("popup", popup)
        page.on("close", closed)
        return resource

    async def _projection(self, task: _Task, page: _Page) -> BrowserPage:
        frames = tuple(
            BrowserFrame(
                key,
                safe_browser_url(frame.url),
                _safe_page_text(frame.name)[:64],
            )
            for key, frame in page.frames.items()
            if not frame.is_detached()
        )
        title = "" if page.dialog is not None else (await page.page.title())[:512]
        return BrowserPage(
            page.id,
            task.id,
            task.incarnation,
            safe_browser_url(page.page.url),
            _safe_page_text(title),
            frames,
        )

    async def _tasks(self, session: str) -> tuple[BrowserTask, ...]:
        result = []
        for task in tuple(self.tasks.values()):
            if task.session_id != session:
                continue
            pages = tuple(
                [
                    await self._projection(task, page)
                    for page in tuple(task.pages.values())
                    if not page.page.is_closed()
                ]
            )
            result.append(BrowserTask(task.id, task.label, task.incarnation, pages))
        return tuple(result)

    async def _result(
        self,
        authority: BrowserAuthority,
        *,
        task: _Task | None = None,
        page: _Page | None = None,
        content: str | None = None,
        truncated: bool = False,
        refs: tuple[BrowserElementRef, ...] = (),
        capture: BrowserCapture | None = None,
        popup: BrowserPage | None = None,
        download: BrowserCapture | None = None,
        action_state: Literal["none", "dispatched", "dialog_pending"] = "none",
    ) -> BrowserResult:
        dialog = None
        if page is not None and page.dialog is not None:
            assert page.dialog_id is not None
            message = _safe_page_text(page.dialog.message)
            dialog = BrowserDialog(page.dialog_id, page.dialog.type, message)
        if page is not None and page.pending is not None and action_state == "none":
            action_state = "dialog_pending"
        truncated = truncated or any(
            len(p.page.frames) > len(p.frames)
            for t in self.tasks.values()
            if t.session_id == authority.session_id
            for p in t.pages.values()
        )
        return BrowserResult(
            await self._tasks(authority.session_id),
            None
            if task is None or page is None or page.page.is_closed()
            else await self._projection(task, page),
            content,
            truncated,
            refs,
            capture,
            popup,
            download,
            dialog,
            action_state,
        )

    async def execute(self, command: BrowserCommand) -> BrowserResult:
        """Execute a typed command, returning verified state or raising failure."""
        self._authority(command.authority)
        try:
            match command:
                case BrowserOpenCommand():
                    return await self._open(command)
                case BrowserObserveCommand():
                    return await self._observe(command)
                case BrowserActCommand():
                    return await self._act(command)
                case _:
                    assert_never(command)
        except asyncio.CancelledError:
            raise
        except BrowserFailure:
            raise
        except PlaywrightTimeoutError:
            raise BrowserFailure(
                "browser_deadline",
                "Browser operation deadline reached; "
                "reobserve before deciding another action",
            ) from None
        except Error:
            raise BrowserFailure(
                "browser_outcome_unknown",
                "Browser operation failed; its site outcome is not confirmed "
                "and must not be replayed",
            ) from None

    async def _open(self, command: BrowserOpenCommand) -> BrowserResult:
        directory = self._authority(command.authority)
        if command.task_id is None:
            if (
                len(self.tasks) >= _MAX_TASKS
                or sum(
                    t.session_id == command.authority.session_id
                    for t in self.tasks.values()
                )
                >= _MAX_SESSION_TASKS
            ):
                raise BrowserFailure(
                    "browser_resource_exhausted", "Browser task limit reached"
                )
            task = _Task(
                uuid.uuid4().hex,
                command.authority.session_id,
                (command.label or "Browser task")[:256],
                uuid.uuid4().hex,
                directory,
            )
            self.tasks[task.id] = task
        else:
            task = self._task(command.authority, command.task_id)
        try:
            return await self._open_page(command, task)
        finally:
            if not task.pages:
                self.tasks.pop(task.id, None)

    async def _open_page(
        self, command: BrowserOpenCommand, task: _Task
    ) -> BrowserResult:
        async with task.guard.interaction(uuid.uuid4().hex):
            if len(task.pages) >= _MAX_PAGES:
                raise BrowserFailure(
                    "browser_resource_exhausted", "Browser task page limit reached"
                )
            context = await self._context(command.authority)
            native = await context.new_page()
            try:
                page = self._register(task, native)
            except BrowserFailure:
                await native.close()
                raise
            if command.url is not None:
                navigation = BrowserAction(
                    kind="navigate",
                    ref=None,
                    observation_id=None,
                    text=None,
                    url=_url(command.url),
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
                    timeout_ms=30000,
                )
                await self._dispatch_or_dialog(
                    task, page, page.page.main_frame, navigation
                )
        return await self._result(command.authority, task=task, page=page)

    async def _observe(self, command: BrowserObserveCommand) -> BrowserResult:
        if command.target is None:
            return await self._result(command.authority)
        task, page, frame = self.target(command.authority, command.target)
        if command.view == "status" or page.dialog is not None:
            return await self._result(command.authority, task=task, page=page)
        capture = None
        refs: tuple[BrowserElementRef, ...] = ()
        content = None
        truncated = False
        if command.view == "image":
            if command.capture_full_page:
                dimensions = await page.page.evaluate(
                    "() => [document.documentElement.scrollWidth, "
                    "document.documentElement.scrollHeight]"
                )
                if (
                    not isinstance(dimensions, list)
                    or len(dimensions) != 2
                    or not all(
                        isinstance(v, (int, float)) and 0 < v <= 32768
                        for v in dimensions
                    )
                    or dimensions[0] * dimensions[1] > 16000000
                ):
                    raise BrowserFailure(
                        "browser_capture_oversized",
                        "Full-page capture exceeds the pixel bound",
                    )
            path = self._output_path(task, "capture", ".png")
            if command.target.frame_id is None:
                data = await page.page.screenshot(
                    path=path,
                    type="png",
                    full_page=command.capture_full_page,
                )
            else:
                data = await frame.locator("body").screenshot(path=path, type="png")
            if len(data) > _MAX_CAPTURE_BYTES:
                raise BrowserFailure(
                    "browser_capture_oversized",
                    "Captured image exceeds the model image bound; "
                    "request a narrower capture",
                )
            # PNG IHDR dimensions are exact without image-normalization mutation.
            width, height = (
                int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"),
            )
            capture = BrowserCapture(str(path), "image/png", len(data), width, height)
        elif command.view == "dom":
            observation = uuid.uuid4().hex
            candidates = frame.locator(
                "a,button,input,select,textarea,[role],[tabindex],summary"
            )
            candidate_count = await candidates.count()
            handles = []
            for index in range(min(candidate_count, _MAX_REFS)):
                handle = await candidates.nth(index).element_handle()
                if handle is not None:
                    handles.append(handle)
            entries = []
            frame_id = next(
                (key for key, value in page.frames.items() if value == frame), None
            )
            if frame_id is None:
                raise BrowserFailure(
                    "browser_resource_exhausted",
                    "Browser frame projection limit reached",
                )
            for old_ref in tuple(page.refs.values()):
                await old_ref.handle.dispose()
            page.refs.clear()
            for handle in handles[:_MAX_REFS]:
                if not await handle.is_visible():
                    await handle.dispose()
                    continue
                ref = uuid.uuid4().hex
                tag = await handle.evaluate("e => e.tagName.toLowerCase()")
                label = await handle.evaluate(
                    """e => (e.getAttribute('aria-label') ||
                        e.getAttribute('placeholder') ||
                        (e.labels ? Array.from(e.labels)
                          .map(l=>l.innerText).join(' ') : '') ||
                        e.innerText || e.tagName).slice(0,256)"""
                )
                if not isinstance(tag, str) or not isinstance(label, str):
                    raise BrowserFailure(
                        "browser_observation_failed",
                        "Browser element description is invalid",
                    )
                label = _safe_page_text(label)
                page.refs[ref] = _Reference(handle, observation, frame)
                entries.append(
                    BrowserElementRef(ref, observation, frame_id, tag, label or tag)
                )
            refs = tuple(entries)
            # Do not return input values from unfiltered accessibility snapshots.
            content = "\n".join(
                f"[{entry.id}] {entry.tag}: {entry.label}" for entry in entries
            )
            truncated = candidate_count > _MAX_REFS
        else:
            raw = await frame.evaluate(_DOM_EXTRACT, command.max_characters)
            if (
                not isinstance(raw, dict)
                or not isinstance(raw.get("html"), str)
                or not isinstance(raw.get("truncated"), bool)
            ):
                raise BrowserFailure(
                    "browser_observation_failed",
                    "Browser DOM extraction did not return a valid result",
                )
            html = raw["html"]
            truncated = raw["truncated"]
            content = (
                html
                if command.view == "raw_dom"
                else markdownify(html, heading_style="ATX", strip=["img"])
            )
        if content is not None:
            content = re.sub(
                r"https?://[^\s<>\"]+\?[^\s<>\"]+", "[URL omitted]", content
            )
        if content is not None and len(content) > command.max_characters:
            content = content[: command.max_characters]
            truncated = True
        return await self._result(
            command.authority,
            task=task,
            page=page,
            content=content,
            truncated=truncated,
            refs=refs,
            capture=capture,
        )

    def _reference(
        self, page: _Page, frame: Frame, action: BrowserAction, ref: str | None = None
    ) -> ElementHandle:
        value = page.refs.get(ref or action.ref or "")
        if (
            value is None
            or value.observation_id != action.observation_id
            or value.frame != frame
        ):
            raise BrowserFailure(
                "browser_stale_reference",
                "Browser reference does not belong to the current "
                "observation and frame",
            )
        return value.handle

    def _output_path(self, task: _Task, prefix: str, suffix: str) -> Path:
        root = task.working_directory / "browser-files"
        if root.resolve() != root or root.is_symlink():
            raise BrowserFailure(
                "browser_invalid_path", "Browser output directory is invalid"
            )
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{prefix}-{uuid.uuid4().hex}{suffix}"

    async def _act(self, command: BrowserActCommand) -> BrowserResult:
        task, page, frame = self.target(command.authority, command.target)
        action = command.action
        if frame != page.page.main_frame and action.kind in {
            "back",
            "forward",
            "reload",
            "close_page",
            "dialog",
        }:
            raise BrowserFailure(
                "browser_invalid_target", "Browser action requires the main page target"
            )
        if action.kind == "close_page":
            async with task.guard.interaction(uuid.uuid4().hex):
                if page.pending is not None:
                    page.pending.cancel()
                    await asyncio.gather(page.pending, return_exceptions=True)
                    page.pending = None
                await page.page.close()
            return await self._result(command.authority, action_state="dispatched")
        if action.kind == "dialog":
            if page.dialog is None or page.dialog_id != action.dialog_id:
                raise BrowserFailure(
                    "browser_stale_dialog", "Browser dialog is no longer current"
                )
            async with task.guard.interaction(uuid.uuid4().hex):
                dialog = page.dialog
                page.dialog = None
                page.dialog_id = None
                page.dialog_ready.clear()
                try:
                    if action.accept is True:
                        await dialog.accept(action.text)
                    else:
                        await dialog.dismiss()
                    if page.pending is not None:
                        outcome = await self._await_dispatch_or_dialog(
                            page, page.pending
                        )
                    else:
                        outcome = _ActionOutcome(None, None)
                except asyncio.CancelledError:
                    if page.pending is not None:
                        page.pending.cancel()
                        await asyncio.gather(page.pending, return_exceptions=True)
                        page.pending = None
                    raise
            return await self._result(
                command.authority,
                task=task,
                page=page,
                popup=outcome.popup,
                download=outcome.download,
                action_state="dialog_pending"
                if page.pending is not None
                else "dispatched",
            )
        if page.dialog is not None or page.pending is not None:
            raise BrowserFailure(
                "browser_dialog_pending",
                "Resolve the current page dialog before another action",
            )
        if action.kind == "wait":
            if action.condition == "url":
                assert action.url is not None
                await frame.wait_for_url(_url(action.url), timeout=action.timeout_ms)
            else:
                handle = self._reference(page, frame, action)
                await handle.wait_for_element_state(
                    "visible" if action.condition == "visible" else "hidden",
                    timeout=action.timeout_ms,
                )
            return await self._result(command.authority, task=task, page=page)
        actor = uuid.uuid4().hex
        async with task.guard.interaction(actor):
            self.target(command.authority, command.target)
            page.popup_owner = None
            if page.popup_tracker is not None:
                page.popup_tracker.clear()
            outcome = await self._dispatch_or_dialog(task, page, frame, action)
        return await self._result(
            command.authority,
            task=task,
            page=page,
            popup=outcome.popup,
            download=outcome.download,
            action_state="dialog_pending" if page.pending is not None else "dispatched",
        )

    async def _trigger(
        self, task: _Task, page: _Page, frame: Frame, action: BrowserAction
    ) -> _ActionOutcome:
        if action.expect == "popup":
            async with page.page.expect_popup(timeout=action.timeout_ms) as info:
                await self._dispatch(page, frame, action)
            popup = await self._projection(task, self._register(task, await info.value))
            return _ActionOutcome(popup, None)
        if action.expect == "download":
            async with page.page.expect_download(timeout=action.timeout_ms) as info:
                await self._dispatch(page, frame, action)
            return _ActionOutcome(None, await self._download(task, await info.value))
        await self._dispatch(page, frame, action)
        return _ActionOutcome(None, None)

    async def _dispatch_or_dialog(
        self, task: _Task, page: _Page, frame: Frame, action: BrowserAction
    ) -> _ActionOutcome:
        dispatch = asyncio.create_task(self._trigger(task, page, frame, action))
        page.pending = dispatch
        dispatch.add_done_callback(_observe_pending_failure)
        return await self._await_dispatch_or_dialog(page, dispatch)

    async def _await_dispatch_or_dialog(
        self, page: _Page, dispatch: asyncio.Task[_ActionOutcome]
    ) -> _ActionOutcome:
        dialog = asyncio.create_task(page.dialog_ready.wait())
        try:
            done, _ = await asyncio.wait(
                (dispatch, dialog), return_when=asyncio.FIRST_COMPLETED
            )
            if dispatch in done:
                try:
                    return await dispatch
                finally:
                    page.pending = None
            return _ActionOutcome(None, None)
        except asyncio.CancelledError:
            dispatch.cancel()
            await asyncio.gather(dispatch, return_exceptions=True)
            page.pending = None
            raise
        finally:
            dialog.cancel()
            await asyncio.gather(dialog, return_exceptions=True)

    async def _dispatch(self, page: _Page, frame: Frame, action: BrowserAction) -> None:
        handle = None
        if action.ref is not None:
            handle = self._reference(page, frame, action)
            if not await handle.evaluate("e => e.isConnected"):
                raise BrowserFailure(
                    "browser_stale_reference", "Browser element is detached"
                )
        match action.kind:
            case "navigate":
                assert action.url is not None
                await frame.goto(
                    _url(action.url),
                    wait_until="domcontentloaded",
                    timeout=action.timeout_ms,
                )
            case "back":
                await page.page.go_back(
                    wait_until="domcontentloaded", timeout=action.timeout_ms
                )
            case "forward":
                await page.page.go_forward(
                    wait_until="domcontentloaded", timeout=action.timeout_ms
                )
            case "reload":
                await page.page.reload(
                    wait_until="domcontentloaded", timeout=action.timeout_ms
                )
            case "click":
                assert handle is not None
                await handle.click(timeout=action.timeout_ms)
            case "fill":
                assert handle is not None and action.text is not None
                await handle.fill(action.text, timeout=action.timeout_ms)
            case "select":
                assert handle is not None and action.values is not None
                await handle.select_option(
                    value=list(action.values), timeout=action.timeout_ms
                )
            case "check":
                assert handle is not None and action.checked is not None
                await handle.set_checked(action.checked, timeout=action.timeout_ms)
            case "press":
                assert action.key is not None
                if handle is None:
                    if frame != page.page.main_frame:
                        raise BrowserFailure(
                            "browser_invalid_target",
                            "Frame key input requires an observed element reference",
                        )
                    await page.page.keyboard.press(action.key)
                else:
                    await handle.press(action.key, timeout=action.timeout_ms)
            case "scroll":
                assert action.x is not None and action.y is not None
                await frame.evaluate(
                    "delta => window.scrollBy(delta.x, delta.y)",
                    {"x": action.x, "y": action.y},
                )
            case "close_page":
                await page.page.close()
            case "hover":
                assert handle is not None
                await handle.hover(timeout=action.timeout_ms)
            case "drag":
                assert handle is not None
                end = self._reference(page, frame, action, action.end_ref)
                start_box, end_box = (
                    await handle.bounding_box(),
                    await end.bounding_box(),
                )
                if start_box is None or end_box is None:
                    raise BrowserFailure(
                        "browser_invalid_target", "Drag targets must be visible"
                    )
                try:
                    await page.page.mouse.move(
                        start_box["x"] + start_box["width"] / 2,
                        start_box["y"] + start_box["height"] / 2,
                    )
                    await page.page.mouse.down()
                    await page.page.mouse.move(
                        end_box["x"] + end_box["width"] / 2,
                        end_box["y"] + end_box["height"] / 2,
                    )
                finally:
                    await page.page.mouse.up()
            case "upload":
                assert handle is not None and action.paths is not None
                paths = [Path(path) for path in action.paths]
                if any(not path.is_absolute() or not path.is_file() for path in paths):
                    raise BrowserFailure(
                        "browser_invalid_path",
                        "Upload requires existing absolute Runtime files",
                    )
                tag = await handle.evaluate("e => e.tagName.toLowerCase()")
                control_type = await handle.get_attribute("type")
                if tag == "input" and control_type == "file":
                    await handle.set_input_files(paths, timeout=action.timeout_ms)
                else:
                    async with page.page.expect_file_chooser(
                        timeout=action.timeout_ms
                    ) as chooser:
                        await handle.click(timeout=action.timeout_ms)
                    await (await chooser.value).set_files(
                        paths, timeout=action.timeout_ms
                    )
            case "dialog" | "wait":
                raise BrowserFailure(
                    "browser_invalid_action",
                    "Browser action requires its dedicated dispatch boundary",
                )
            case _:
                assert_never(action.kind)

    async def _download(self, task: _Task, download: Download) -> BrowserCapture:
        suffix = Path(download.suggested_filename).suffix[:16]
        if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", suffix) is None:
            suffix = ""
        path = self._output_path(task, "download", suffix)
        await download.save_as(path)
        if await download.failure() is not None:
            raise BrowserFailure("browser_download_failed", "Browser download failed")
        return BrowserCapture(
            str(path),
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            path.stat().st_size,
            None,
            None,
        )

    async def close(self) -> None:
        """Invalidate all live handles while retaining native profile bytes."""
        self.closed = True
        pending = [
            page.pending
            for task in self.tasks.values()
            for page in task.pages.values()
            if page.pending is not None
        ]
        for operation in pending:
            operation.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        cleanup_failed = False
        try:
            for context in tuple(self.contexts.values()):
                try:
                    await context.close()
                except asyncio.CancelledError:
                    raise
                except Error:
                    cleanup_failed = True
        finally:
            self.contexts.clear()
            self.tasks.clear()
            if self.driver is not None:
                driver, self.driver = self.driver, None
                try:
                    await driver.stop()
                except asyncio.CancelledError:
                    raise
                except Error:
                    cleanup_failed = True
        if cleanup_failed:
            raise BrowserFailure(
                "browser_cleanup_failed", "Browser resource cleanup failed"
            )


def _observe_pending_failure(operation: asyncio.Task[_ActionOutcome]) -> None:
    if not operation.cancelled():
        operation.exception()


def _safe_page_text(text: str) -> str:
    """Bound page descriptions and omit private URLs."""
    return re.sub(r"https?://[^\s<>]+", "[URL omitted]", text)[:512]


def _sandbox_unavailable(message: str) -> bool:
    """Classify native sandbox diagnostics, never generic startup errors."""
    return any(
        marker in message
        for marker in (
            "No usable sandbox!",
            "Failed to move to new namespace",
            "Running as root without --no-sandbox is not supported",
        )
    )


_DOM_EXTRACT = """(budget) => {
  let count = 0; let limited = false;
  const clean = node => {
    if (++count > 10000) { limited = true; return null; }
    if (node.nodeType === Node.TEXT_NODE)
      return document.createTextNode(node.textContent || '');
    if (!(node instanceof Element)) return null;
    const style = getComputedStyle(node);
    const excluded = ['SCRIPT','STYLE','NOSCRIPT','TEMPLATE'];
    if (excluded.includes(node.tagName) || style.display === 'none' ||
        style.visibility === 'hidden' || node.hidden) return null;
    const copy = document.createElement(node.tagName);
    for (const name of ['id','role','type','aria-label','aria-disabled','disabled',
                        'for','name','placeholder']) {
      if (node.hasAttribute(name)) copy.setAttribute(name,node.getAttribute(name));
    }
    if (['INPUT','TEXTAREA'].includes(node.tagName)) return copy;
    if (node.tagName === 'A') {
      try {
        const u = new URL(node.getAttribute('href'),location.href);
        if (['http:','https:'].includes(u.protocol))
          copy.setAttribute('href',u.origin+u.pathname);
      } catch { /* Invalid page link is omitted from the exported view. */ }
    }
    for (const child of node.childNodes) {
      if (count >= 10000) { limited = true; break; }
      const safe = clean(child); if (safe) copy.appendChild(safe);
    }
    return copy;
  };
  const root = clean(document.body || document.documentElement);
  const html = root ? root.outerHTML : '';
  return {html:html.slice(0,budget),truncated:limited || html.length > budget};
}"""
