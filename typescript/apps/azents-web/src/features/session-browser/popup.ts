import { sameBrowserTarget } from "./input.ts";
import type { BrowserStatus, BrowserTarget } from "./types";

export interface BrowserPopupHint {
  resourceKey: string;
  attachment: string;
  navigation: string;
  origin: BrowserTarget;
  target: BrowserTarget;
}

/** Projection refresh cannot promote a hint from a lost/replaced attachment. */
export function browserPopupHintCurrent(
  hint: BrowserPopupHint,
  resourceKey: string,
  status: BrowserStatus | null,
  selected: BrowserTarget | null,
  connected: boolean,
  dismissedAttachment: string | null,
): boolean {
  return (
    connected &&
    hint.attachment !== dismissedAttachment &&
    hint.resourceKey === resourceKey &&
    status !== null &&
    status.state === "connected" &&
    status.allow_input &&
    status.attachment_id === hint.attachment &&
    status.navigation_id === hint.navigation &&
    selected !== null &&
    sameBrowserTarget(hint.origin, selected) &&
    sameBrowserTarget(hint.origin, status.target) &&
    status.opened_target !== null &&
    sameBrowserTarget(hint.target, status.opened_target)
  );
}
