import { sameBrowserTarget } from "./input.ts";
import type { BrowserPageChoice, BrowserViewState } from "./types";
import type { BrowserLinkedTarget } from "@/shared/session-browser/route";

/** Explicit live links win; stale/missing links select recent Agent work, then the first live tab. */
export function browserProjectionState(
  pages: readonly BrowserPageChoice[],
  linked: BrowserLinkedTarget,
  allowInput: boolean,
  recent: readonly BrowserPageChoice["target"][] = [],
): BrowserViewState {
  if (pages.length === 0) {
    return { type: "EMPTY" };
  }
  const selected =
    (linked.type === "TARGET"
      ? pages.find((page) => sameBrowserTarget(page.target, linked.target))
      : null) ??
    recent.flatMap((target) =>
      pages.filter((page) => sameBrowserTarget(page.target, target)),
    )[0] ??
    pages[0] ??
    null;
  if (selected === null) {
    return { type: "EMPTY" };
  }
  return {
    type: "READY",
    pages,
    selected,
    connection: "connecting",
    image: null,
    status: null,
    canInput: false,
    canClose: allowInput,
    dialog: null,
    conflict: false,
    outcomeUnknown: false,
  };
}
