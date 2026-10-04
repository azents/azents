import type {
  ExternalChannelFilesDetailResponse,
  HistoricalMemoryExecutionDetailResponse,
  PlatformGitHubAppDetailResponse,
  SystemSettingAuditEventResponse,
} from "@azents/admin-client";

export type ExternalChannelFilesPageState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; detail: ExternalChannelFilesDetailResponse };

export type PlatformGitHubAppPageState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; detail: PlatformGitHubAppDetailResponse };

export type SystemSettingAuditState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      events: SystemSettingAuditEventResponse[];
      total: number;
    };

export interface PlatformGitHubAppDraft {
  appId: string;
  clientId: string;
  privateKey: string;
  clientSecret: string;
  appIdTouched: boolean;
  clientIdTouched: boolean;
  clearPrivateKey: boolean;
  clearClientSecret: boolean;
}

export interface ExternalChannelFilesDraft {
  outboundMaxFileMiB: number | string;
  outboundMaxActionMiB: number | string;
}

export type HistoricalMemoryExecutionPageState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; detail: HistoricalMemoryExecutionDetailResponse };

export interface HistoricalMemoryExecutionDraft {
  maxTurns: number | string;
  timeoutSeconds: number | string;
}
