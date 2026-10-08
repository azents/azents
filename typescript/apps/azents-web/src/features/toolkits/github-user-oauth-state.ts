import { z } from "zod/v4";
import type {
  GitHubSetupAvailability,
  GitHubUserCandidateSummary,
  GitHubUserConnectionSummary,
  GitHubUserInstallation,
} from "@azents/public-client";

export const GITHUB_USER_CONTEXT_KEY = "azents.github-user.origin";
export const GITHUB_USER_COMPLETION_EVENT = "azents-github-user-complete";
const contextSchema = z
  .object({
    handle: z.string().min(1),
    toolkitId: z.string().min(1),
    agentId: z.string().min(1).optional(),
    returnPath: z.string().startsWith("/w/"),
    returnView: z.enum(["DETAIL", "EDIT"]),
    reviewAttemptId: z
      .string()
      .regex(/^[a-zA-Z0-9_-]{1,64}$/)
      .optional(),
  })
  .strict();
export type GitHubUserContext = z.infer<typeof contextSchema>;

/** Resume only the exact Toolkit ownership context; the server admits review. */
export function gitHubUserResumeMatches(
  saved: GitHubUserContext | null,
  current: GitHubUserContext,
): saved is GitHubUserContext & { reviewAttemptId: string } {
  return (
    saved?.reviewAttemptId != null &&
    saved.handle === current.handle &&
    saved.toolkitId === current.toolkitId &&
    saved.agentId === current.agentId &&
    saved.returnPath === current.returnPath
  );
}

export interface GitHubUserPopupHandoff<Popup> {
  toolkitId: string;
  popup: Popup;
}

/** Acceptance clears only this handoff, not a newer explicitly reserved popup. */
export function consumeGitHubUserPopupHandoff<Popup>(
  current: GitHubUserPopupHandoff<Popup> | null,
  acceptedPopup: Popup,
): GitHubUserPopupHandoff<Popup> | null {
  return current?.popup === acceptedPopup ? null : current;
}

export function parseGitHubUserContext(
  value: unknown,
): GitHubUserContext | null {
  const result = contextSchema.safeParse(value);
  return result.success ? result.data : null;
}
export function deserializeGitHubUserContext(
  value?: string,
): GitHubUserContext | null {
  if (!value) {
    return null;
  }
  try {
    return parseGitHubUserContext(JSON.parse(value));
  } catch {
    return null;
  }
}
export function parseGitHubUserState(state: string | null): string | null {
  if (state == null) {
    return null;
  }
  const parts = state.split(".");
  return parts.length === 3 &&
    parts[0] === "github_user" &&
    /^[a-zA-Z0-9_-]{1,64}$/.test(parts[1] ?? "") &&
    /^[a-zA-Z0-9_-]+$/.test(parts[2] ?? "")
    ? (parts[1] ?? null)
    : null;
}
export function isGitHubUserMode(value: unknown): boolean {
  return value === "github_app_user" || value === "github_app_platform_user";
}
const completion = z
  .object({
    type: z.literal(GITHUB_USER_COMPLETION_EVENT),
    attempt_id: z.string().min(1),
  })
  .strict();
export function decodeGitHubUserCompletion(
  event: { origin: string; source: unknown; data: unknown },
  origin: string,
  popup: unknown,
  attemptId: string | null,
): boolean {
  if (
    popup == null ||
    attemptId == null ||
    event.origin !== origin ||
    event.source !== popup
  ) {
    return false;
  }
  const data = completion.safeParse(event.data);
  return data.success && data.data.attempt_id === attemptId;
}

export type GitHubAvailabilityState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; availability: GitHubSetupAvailability };
export type GitHubUserSetupState =
  | { type: "IDLE" }
  | { type: "STARTING" }
  | { type: "WAITING"; attemptId: string; installUrl: string }
  | { type: "REVIEW_LOADING"; attemptId: string }
  | { type: "REVIEW"; candidate: GitHubUserCandidateSummary }
  | { type: "CONFIRMING"; candidate: GitHubUserCandidateSummary }
  | { type: "CANCELLING"; attemptId: string }
  | { type: "ERROR"; reason: GitHubUserUiError; attemptId: string | null };
export type GitHubUserUiError =
  | "popupBlocked"
  | "popupClosed"
  | "setupFailed"
  | "reviewFailed"
  | "stale"
  | "authority"
  | "incompatible"
  | "disconnectFailed";
export type GitHubUserStatusState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      connection: GitHubUserConnectionSummary | null;
    };
export type GitHubUserAccessState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | {
      type: "READY";
      installations: GitHubUserInstallation[];
      nextCursor: string | null;
    }
  | {
      type: "MORE";
      installations: GitHubUserInstallation[];
      nextCursor: string;
    }
  | {
      type: "ERROR";
      installations: GitHubUserInstallation[];
      nextCursor: string | null;
    };
export type GitHubUserOperationState =
  | { type: "IDLE" }
  | { type: "DISCONNECT_CONFIRM" }
  | { type: "DISCONNECTING" }
  | { type: "ERROR"; reason: GitHubUserUiError };

/** A continuation can repeat an owner, including within the same response. */
export function mergeGitHubUserAccess(
  existing: GitHubUserInstallation[],
  incoming: GitHubUserInstallation[],
): GitHubUserInstallation[] {
  const owners = new Map(
    existing.map((owner) => [owner.installation_id, owner]),
  );
  for (const owner of incoming) {
    const prior = owners.get(owner.installation_id);
    const repositories = new Map(
      (prior?.repositories ?? []).map((repo) => [repo.repository_id, repo]),
    );
    for (const repo of owner.repositories) {
      repositories.set(repo.repository_id, repo);
    }
    owners.set(owner.installation_id, {
      ...owner,
      repositories: [...repositories.values()],
      failure_reason: owner.failure_reason ?? prior?.failure_reason ?? null,
      repositories_complete:
        owner.repositories_complete && (prior?.failure_reason ?? null) == null,
    });
  }
  return [...owners.values()];
}
const errorShape = z.object({
  data: z.object({ apiError: z.object({ code: z.string().nullable() }) }),
});
export function githubUserErrorReason(
  error: unknown,
  fallback: GitHubUserUiError,
): GitHubUserUiError {
  const result = errorShape.safeParse(error);
  if (!result.success) {
    return fallback;
  }
  switch (result.data.data.apiError.code) {
    case "stale":
      return "stale";
    case "authority":
      return "authority";
    case "invalid":
      return "incompatible";
    default:
      return fallback;
  }
}
