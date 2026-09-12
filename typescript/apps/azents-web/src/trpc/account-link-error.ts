import { ApiError } from "./api-error.ts";

export const ACCOUNT_LINK_FAILURE_REASONS = [
  "membership_required",
  "elevation_required",
  "resource_not_found",
  "expired",
  "conflict",
  "candidate_not_ready",
  "candidate_terminal",
  "unavailable",
  "busy",
] as const;

export type AccountLinkApiFailureReason =
  (typeof ACCOUNT_LINK_FAILURE_REASONS)[number];

const ELEVATION_REQUIRED_MESSAGE = "Elevated access required";

function apiDetailCode(error: ApiError): string | null {
  if (
    typeof error.body !== "object" ||
    error.body === null ||
    !("detail" in error.body) ||
    typeof error.body.detail !== "object" ||
    error.body.detail === null ||
    !("code" in error.body.detail) ||
    typeof error.body.detail.code !== "string"
  ) {
    return null;
  }
  return error.body.detail.code;
}

export function accountLinkFailureReason(
  error: unknown,
): AccountLinkApiFailureReason | null {
  if (!(error instanceof ApiError)) {
    return null;
  }
  if (error.status === 403 && error.message === ELEVATION_REQUIRED_MESSAGE) {
    return "elevation_required";
  }
  const code = apiDetailCode(error);
  return ACCOUNT_LINK_FAILURE_REASONS.find((reason) => reason === code) ?? null;
}
