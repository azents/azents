import { sameBrowserTarget } from "./input.ts";
import type { BrowserLinkedTarget } from "./route";
import type { BrowserPageChoice, BrowserViewState } from "./types";

/** Pure selection never promotes a missing linked page to a different live page. */
export function browserProjectionState(
  pages: readonly BrowserPageChoice[],
  linked: BrowserLinkedTarget,
  allowInput: boolean,
): BrowserViewState {
  if (linked.type === "INVALID") {
    return { type: "CLOSED_TARGET", pages };
  }
  const selected =
    linked.type === "TARGET"
      ? pages.find((page) => sameBrowserTarget(page.target, linked.target))
      : null;
  if (linked.type === "TARGET" && !selected) {
    return { type: "CLOSED_TARGET", pages };
  }
  if (pages.length === 0) {
    return { type: "EMPTY" };
  }
  if (!selected) {
    return { type: "SELECT_PAGE", pages };
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
