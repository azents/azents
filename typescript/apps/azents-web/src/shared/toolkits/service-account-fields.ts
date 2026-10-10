import { getOptionalString, isRecord } from "../lib/unknown-value.ts";
/** Preserve the existing provider form's accepted Service Account key shape. */
export function getServiceAccountKey(
  value: unknown,
): Record<string, unknown> | null {
  return isRecord(value) && getOptionalString(value.client_email)
    ? value
    : null;
}
