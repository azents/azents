"""Content-free, document-local text-input geometry for native mobile receivers."""

import uuid
from dataclasses import asdict, dataclass

from azents_runtime_control.browser_viewer_contract import (
    ViewerEditable,
    decode_viewer_editables,
)
from playwright.async_api import Error, Frame, JSHandle, Page

_PROBE = """() => {
    const ids = new WeakMap(); let sequence = 0;
    const modes = new Set(['text','email','url','tel','numeric','decimal','search']);
    const types = new Set(['text','email','url','tel','password','search','number']);
    const hit = (root, x, y) => {
        let element = root.elementFromPoint(x, y);
        while (element?.shadowRoot) {
            const inner = element.shadowRoot.elementFromPoint(x, y);
            if (!inner || inner === element) break;
            element = inner;
        }
        return element;
    };
    const probe = () => {
        const candidates = []; let visited = 0;
        const walk = root => {
            for (const element of root.querySelectorAll('*')) {
                if (++visited > 5000) break;
                if (element.shadowRoot) walk(element.shadowRoot);
                if (element.matches('textarea,input,[contenteditable]')) {
                    candidates.push(element);
                }
            }
        };
        walk(document);
        const regions = [];
        for (const element of candidates) {
            if (regions.length >= 16) break;
            const input = element instanceof HTMLInputElement;
            const native = input || element instanceof HTMLTextAreaElement;
            if (element.inputMode === 'none') continue;
            if (native) {
                if (element.matches(':disabled') || element.readOnly ||
                    (input && !types.has(element.type))) continue;
            } else if (!element.isContentEditable ||
                element.parentElement?.isContentEditable) continue;
            const rect = element.getBoundingClientRect();
            let x = Math.max(0, rect.left), y = Math.max(0, rect.top);
            let right = Math.min(innerWidth, rect.right);
            let bottom = Math.min(innerHeight, rect.bottom);
            for (let parent = element.parentElement; parent;
                parent = parent.parentElement) {
                const style = getComputedStyle(parent);
                const bounds = parent.getBoundingClientRect();
                if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) {
                    x=Math.max(x,bounds.left);right=Math.min(right,bounds.right);
                }
                if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) {
                    y=Math.max(y,bounds.top);bottom=Math.min(bottom,bounds.bottom);
                }
            }
            if (right - x < 4 || bottom - y < 4) continue;
            const points = [[x+1,y+1],[right-1,y+1],
                [x+1,bottom-1],[right-1,bottom-1],[(x+right)/2,(y+bottom)/2]];
            if (!points.every(([px,py]) => {
                const target=hit(document,px,py);
                return target && (target===element || element.contains(target));
            })) continue;
            if (!ids.has(element)) ids.set(element, String(++sequence));
            const input_mode = modes.has(element.inputMode) ? element.inputMode :
                ['email','url','tel','search'].includes(element.type) ?
                element.type : element.type === 'number' ? 'decimal' : 'text';
            regions.push({id:ids.get(element),x,y,
                width:right-x,height:bottom-y,input_mode});
        }
        return regions;
    };
    probe.focused = id => {
        let active = document.activeElement;
        while (active?.shadowRoot?.activeElement)
            active=active.shadowRoot.activeElement;
        return active?.isConnected && ids.get(active) === id &&
            probe().some(region => region.id === id);
    };
    return probe;
}"""

_FRAME_PROJECT = """(element, regions) => {
    for (let parent=element;parent;) {
        const style=getComputedStyle(parent);
        if (style.transform !== 'none' || Number(style.zoom || 1) !== 1) return [];
        const root=parent.getRootNode();
        parent=parent.parentElement ||
            (root instanceof ShadowRoot ? root.host : null);
    }
    const rect = element.getBoundingClientRect();
    if (Math.abs(rect.width - element.offsetWidth) >= 0.5 ||
        Math.abs(rect.height - element.offsetHeight) >= 0.5 ||
        getComputedStyle(element).transform !== 'none') return [];
    const hit = (x,y) => {
        let target = document.elementFromPoint(x,y);
        while (target?.shadowRoot) {
            const inner = target.shadowRoot.elementFromPoint(x,y);
            if (!inner || inner===target) break;
            target=inner;
        }
        return target===element;
    };
    return regions.map(region => ({...region,
        x:region.x + rect.left + element.clientLeft,
        y:region.y + rect.top + element.clientTop})).filter(region => {
        const {x,y,width,height}=region;
        return x>=0 && y>=0 && x+width<=innerWidth && y+height<=innerHeight &&
            [[x+1,y+1],[x+width-1,y+1],[x+1,y+height-1],
             [x+width-1,y+height-1],[x+width/2,y+height/2]]
            .every(([px,py])=>hit(px,py));
    });
}"""


@dataclass
class _Probe:
    prefix: str
    handle: JSHandle


class BrowserEditableRegions:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.probes: dict[Frame, _Probe] = {}

    async def read(self) -> tuple[ViewerEditable, ...]:
        result: list[ViewerEditable] = []
        viewport = self.page.viewport_size
        if viewport is None:
            return ()
        for frame in self.page.frames[:16]:
            if frame.is_detached():
                continue
            probe = self.probes.get(frame)
            try:
                if probe is None:
                    probe = _Probe(
                        uuid.uuid4().hex[:12], await frame.evaluate_handle(_PROBE)
                    )
                    self.probes[frame] = probe
                regions = decode_viewer_editables(
                    await probe.handle.evaluate("probe => probe()"), 32768, 32768
                )
                current = frame
                while current.parent_frame is not None:
                    element = await current.frame_element()
                    regions = decode_viewer_editables(
                        await element.evaluate(
                            _FRAME_PROJECT, [asdict(r) for r in regions]
                        ),
                        32768,
                        32768,
                    )
                    current = current.parent_frame
                for region in regions:
                    if len(result) >= 16:
                        break
                    left, top = round(region.x, 2), round(region.y, 2)
                    width, height = round(region.width, 2), round(region.height, 2)
                    if (
                        left < 0
                        or top < 0
                        or left + width > viewport["width"]
                        or top + height > viewport["height"]
                    ):
                        continue
                    result.append(
                        ViewerEditable(
                            f"{probe.prefix}-{region.id}",
                            left,
                            top,
                            width,
                            height,
                            region.input_mode,
                        )
                    )
            except Error as error:
                if not any(
                    signature in error.message.lower()
                    for signature in (
                        "execution context was destroyed",
                        "cannot find context",
                        "frame was detached",
                        "frame has been detached",
                        "target page, context or browser has been closed",
                    )
                ):
                    raise
                self.probes.pop(frame, None)
                # Retire only this document; unrelated native receivers survive.
                continue
        for frame in tuple(self.probes):
            if frame not in self.page.frames:
                probe = self.probes.pop(frame)
                await probe.handle.dispose()
        return tuple(result)

    async def close(self) -> None:
        for probe in self.probes.values():
            await probe.handle.dispose()
        self.probes.clear()

    async def focused(self, identifier: str) -> bool:
        """Check the same current editable and every active ancestor frame."""
        if not any(region.id == identifier for region in await self.read()):
            return False
        for frame, probe in tuple(self.probes.items()):
            prefix = f"{probe.prefix}-"
            if not identifier.startswith(prefix):
                continue
            try:
                if not await probe.handle.evaluate(
                    "(probe, id) => probe.focused(id)", identifier.removeprefix(prefix)
                ):
                    return False
                current = frame
                while current.parent_frame is not None:
                    element = await current.frame_element()
                    if not await element.evaluate("""element => {
                        let active = document.activeElement;
                        while (active?.shadowRoot?.activeElement)
                            active = active.shadowRoot.activeElement;
                        return active === element;
                    }"""):
                        return False
                    current = current.parent_frame
                return True
            except Error as error:
                if any(
                    signature in error.message.lower()
                    for signature in (
                        "execution context was destroyed",
                        "cannot find context",
                        "frame was detached",
                        "frame has been detached",
                        "target page, context or browser has been closed",
                    )
                ):
                    return False
                raise
        return False
