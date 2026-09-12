import type {
  AccountLinkFailureReason,
  ExternalAccountCandidateStatus,
  ExternalAccountLinkStatus,
} from "./types";

export type CandidateNextAction =
  "check_status" | "confirm" | "connected" | "start_fresh";

export type ElevationScreenState = "loading" | "ready" | "error";

export function elevationScreenState({
  hasResponse,
  isError,
}: {
  hasResponse: boolean;
  isError: boolean;
}): ElevationScreenState {
  if (hasResponse) {
    return "ready";
  }
  return isError ? "error" : "loading";
}

export function preserveLastSafeOrigin<T>(
  current: T | null,
  previous: T | null,
): T | null {
  return current ?? previous;
}

export function candidateNextAction(
  status: ExternalAccountCandidateStatus,
): CandidateNextAction {
  switch (status) {
    case "pending_provider_proof":
      return "check_status";
    case "provider_verified":
      return "confirm";
    case "connected":
      return "connected";
    case "cancelled":
    case "expired":
      return "start_fresh";
  }
}

export function accountLinkStatusColor(
  status: ExternalAccountLinkStatus,
): "green" | "gray" | "yellow" {
  switch (status) {
    case "active":
      return "green";
    case "inactive":
      return "yellow";
    case "revoked":
      return "gray";
  }
}

export function isRecoverableWithFreshCandidate(
  reason: AccountLinkFailureReason,
): boolean {
  return (
    reason === "expired" ||
    reason === "candidate_terminal" ||
    reason === "resource_not_found"
  );
}
