/** Toolkit feature state type */

import type {
  GitHubSetupAvailability,
  GitHubUserCandidateSummary,
  GitHubUserConnectionSummary,
  GitHubUserInstallation,
  ToolkitConfigResponse,
  ToolkitResponse,
} from "@azents/public-client";

/** Toolkit Config list state */
export type ToolkitConfigListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; configs: ToolkitConfigResponse[] };

/** Toolkit Config form state */
export type ToolkitConfigFormState =
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | { type: "CREATE" }
  | { type: "EDIT"; config: ToolkitConfigResponse };

/** Mutation state */
export type MutationState =
  { type: "IDLE"; error: string | null } | { type: "SUBMITTING" };

/** Toolkit (tool definition) list state */
export type ToolkitListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; toolkits: ToolkitResponse[] };

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

export type GitHubUserOAuthCallbackState =
  | { type: "LOADING" }
  | { type: "COMPLETE" }
  | { type: "ERROR"; reason: GitHubUserUiError };

export type GithubConnectionTestState =
  | { type: "IDLE" }
  | { type: "TESTING" }
  | { type: "RESULT"; success: boolean; message: string };

export interface InstallationTarget {
  installation_id: string;
  account_login: string;
  account_type: string;
  account_avatar_url: string | null;
}
export interface InstallationItem {
  id: number;
  account_login: string;
  account_type: string;
  account_avatar_url: string;
}

export type GithubInstallationState =
  | { type: "IDLE"; installations: InstallationItem[] }
  | { type: "LOADING"; installations: InstallationItem[] }
  | { type: "READY"; installations: InstallationItem[] }
  | { type: "ERROR"; installations: InstallationItem[] };
