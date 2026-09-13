import type { ElevationModalContainerProps } from "@/features/security/containers/useElevationModal";
import type { AccountLinkApiFailureReason } from "@/trpc/account-link-error";

export type ExternalAccountProvider = "slack" | "discord";
export type ExternalAccountProviderStatus =
  "not_configured" | "incomplete" | "invalid" | "ready" | "unavailable";

export type AccountLinkFailureReason = AccountLinkApiFailureReason;

export interface ExternalAccountProviderAvailability {
  provider: ExternalAccountProvider;
  status: ExternalAccountProviderStatus;
  available: boolean;
}

export interface ExternalAccountLinkItem {
  id: string;
  provider: ExternalAccountProvider;
  providerTeamLabel: string | null;
  externalDisplayLabel: string;
  linkedAt: string;
}

export type ExternalAccountLinksState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      providers: ExternalAccountProviderAvailability[];
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

export type ExternalAccountOAuthResultState =
  | {
      type: "CONNECTED";
      provider: ExternalAccountProvider;
      externalDisplayLabel: string;
      providerTeamLabel: string | null;
    }
  | { type: "CANCELLED"; provider: ExternalAccountProvider }
  | {
      type: "PROVIDER_UNAVAILABLE";
      provider: ExternalAccountProvider;
      status: ExternalAccountProviderStatus;
    }
  | {
      type: "FAILED";
      provider: ExternalAccountProvider | null;
      reason:
        AccountLinkFailureReason | "invalid_provider" | "invalid_callback";
    }
  | { type: "AUTH_REQUIRED" };
