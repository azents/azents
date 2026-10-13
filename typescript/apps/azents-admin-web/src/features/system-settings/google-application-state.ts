import type {
  GoogleApplicationDetail,
  GoogleApplicationPatchRequest,
} from "@azents/admin-client";

export interface GoogleApplicationDraft {
  clientId: string;
  clientTouched: boolean;
  secret: string;
  clearSecret: boolean;
}
export type GoogleApplicationMutation = Pick<
  GoogleApplicationPatchRequest,
  "expected_version" | "client_id"
> & {
  client_secret?: { action: "replace"; value: string } | { action: "clear" };
};
export function googleApplicationDraft(
  detail: GoogleApplicationDetail,
): GoogleApplicationDraft {
  return {
    clientId: detail.client_id ?? "",
    clientTouched: false,
    secret: "",
    clearSecret: false,
  };
}
export function googleApplicationDirty(draft: GoogleApplicationDraft): boolean {
  return draft.clientTouched || draft.clearSecret || draft.secret.length > 0;
}
/** Preserve omitted fields; a blank touched ID explicitly clears its Admin value. */
export function googleApplicationPatch(
  draft: GoogleApplicationDraft,
  expectedVersion: number,
): GoogleApplicationMutation {
  const patch: GoogleApplicationMutation = {
    expected_version: expectedVersion,
  };
  if (draft.clientTouched) {
    patch.client_id = draft.clientId.trim() || null;
  }
  if (draft.clearSecret) {
    patch.client_secret = { action: "clear" };
  } else if (draft.secret.length > 0) {
    patch.client_secret = { action: "replace", value: draft.secret };
  }
  return patch;
}
