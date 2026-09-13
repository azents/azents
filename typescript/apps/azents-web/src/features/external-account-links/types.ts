import type { ElevationModalContainerProps } from "@/features/security/containers/useElevationModal";

export type ExternalAccountProvider = "slack" | "discord";
export type ExternalAccountLinkStatus = "active" | "inactive" | "revoked";
export type AccountLinkFailureReason =
  | "membership_required"
  | "elevation_required"
  | "resource_not_found"
  | "expired"
  | "conflict"
  | "candidate_not_ready"
  | "candidate_terminal"
  | "unavailable"
  | "busy";

export interface ExternalAccountLinkItem {
  id: string;
  accountContextLabel: string;
  provider: ExternalAccountProvider;
  providerTeamLabel: string;
  externalDisplayLabel: string;
  linkedAt: string;
  status: ExternalAccountLinkStatus;
}

export type ExternalAccountLinksState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      links: ExternalAccountLinkItem[];
      disconnect:
        | { type: "IDLE" }
        | {
            type: "CONFIRMING";
            link: ExternalAccountLinkItem;
            error: AccountLinkFailureReason | null;
          }
        | { type: "SUBMITTING"; link: ExternalAccountLinkItem };
    }
  | {
      type: "ELEVATION_REQUIRED";
      link: ExternalAccountLinkItem;
      elevation: ElevationModalContainerProps;
    }
  | {
      type: "ELEVATION_LOADING";
      link: ExternalAccountLinkItem;
    }
  | {
      type: "ELEVATION_ERROR";
      link: ExternalAccountLinkItem;
      message: string;
    };

export interface ExternalAccountLinkOrigin {
  id: string;
  workspaceName: string;
  workspaceHandle: string;
  provider: ExternalAccountProvider;
  providerTeamLabel: string;
  externalDisplayLabel: string;
  expiresAt: string;
  state: "open" | "cancelled" | "consumed" | "expired";
  candidateCount: number;
  candidateLimit: number;
  returnUrl: string | null;
}

export type ExternalAccountCandidateStatus =
  | "pending_provider_proof"
  | "provider_verified"
  | "connected"
  | "cancelled"
  | "expired";

export interface ExternalAccountCandidate {
  id: string;
  code: string;
  expiresAt: string;
  status: ExternalAccountCandidateStatus;
}

export type ExternalAccountLinkConfirmationState =
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | {
      type: "ORIGIN_UNAVAILABLE";
      reason: "cancelled" | "consumed" | "expired" | "unavailable";
      origin: ExternalAccountLinkOrigin;
      accountEmail: string;
    }
  | { type: "ORIGIN_EXPIRED" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      origin: ExternalAccountLinkOrigin;
      accountEmail: string;
      candidate: ExternalAccountCandidate | null;
      action:
        | { type: "IDLE"; error: AccountLinkFailureReason | null }
        | { type: "CREATING_CANDIDATE" }
        | { type: "CHECKING_STATUS" }
        | { type: "CONFIRMING_LINK" }
        | { type: "CANCELLING" }
        | { type: "SWITCHING_ACCOUNT" };
    }
  | {
      type: "ELEVATION_REQUIRED";
      origin: ExternalAccountLinkOrigin;
      accountEmail: string;
      action: "create_candidate" | "confirm_candidate";
      elevation: ElevationModalContainerProps;
    }
  | {
      type: "ELEVATION_LOADING";
      origin: ExternalAccountLinkOrigin;
      accountEmail: string;
      action: "create_candidate" | "confirm_candidate";
    }
  | {
      type: "ELEVATION_ERROR";
      origin: ExternalAccountLinkOrigin;
      accountEmail: string;
      action: "create_candidate" | "confirm_candidate";
      message: string;
    }
  | {
      type: "CONNECTED";
      origin: ExternalAccountLinkOrigin;
      accountEmail: string;
      workspaceName: string;
      provider: ExternalAccountProvider;
      externalDisplayLabel: string;
      returnUrl: string | null;
    };
