import type {
  GoogleApplicationDetail,
  GoogleApplicationPatchRequest,
} from "@azents/admin-client";

export interface GoogleApplicationDraft {
  clientId: string;
  clientTouched: boolean;
  pickerApiKey: string;
  pickerApiKeyTouched: boolean;
  pickerAppId: string;
  pickerAppIdTouched: boolean;
  secret: string;
  clearSecret: boolean;
}
export type GoogleApplicationMutation = Pick<
  GoogleApplicationPatchRequest,
  "expected_version" | "client_id" | "picker_api_key" | "picker_app_id"
> & {
  client_secret?: { action: "replace"; value: string } | { action: "clear" };
};
export function googleApplicationDraft(
  detail: GoogleApplicationDetail,
): GoogleApplicationDraft {
  return {
    clientId: detail.client_id ?? "",
    clientTouched: false,
    pickerApiKey: detail.picker_api_key ?? "",
    pickerApiKeyTouched: false,
    pickerAppId: detail.picker_app_id ?? "",
    pickerAppIdTouched: false,
    secret: "",
    clearSecret: false,
  };
}
export function googleApplicationDirty(draft: GoogleApplicationDraft): boolean {
  return (
    draft.clientTouched ||
    draft.pickerApiKeyTouched ||
    draft.pickerAppIdTouched ||
    draft.clearSecret ||
    draft.secret.length > 0
  );
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
  if (draft.pickerApiKeyTouched) {
    patch.picker_api_key = draft.pickerApiKey.trim() || null;
  }
  if (draft.pickerAppIdTouched) {
    patch.picker_app_id = draft.pickerAppId.trim() || null;
  }
  if (draft.clearSecret) {
    patch.client_secret = { action: "clear" };
  } else if (draft.secret.length > 0) {
    patch.client_secret = { action: "replace", value: draft.secret };
  }
  return patch;
}
