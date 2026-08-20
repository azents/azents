import type {
  DiscordThreadAutoArchiveDurationMinutes,
  ExternalChannelMultiConnectionImpact,
  ExternalChannelMultiRouteImpact,
  ExternalChannelTransport,
  ManagedChannelDefault,
  ManagedMultiConnection,
  ManagedMultiRoute,
  ManagedSlackManagementHandoff,
} from "@azents/public-client";

export interface SlackCredentialDraft {
  botToken: string;
  signingSecret: string;
  appToken: string;
}

export interface MultiConnectionDraft {
  appId: string;
  transport: ExternalChannelTransport;
  credentials: SlackCredentialDraft;
}

export interface DiscordMultiConnectionDraft {
  appId: string;
  targetGuildId: string;
  threadAutoArchiveDurationMinutes: DiscordThreadAutoArchiveDurationMinutes;
  botToken: string;
}

export type WorkspaceMultiAppsState =
  | { type: "LOADING" }
  | { type: "FORBIDDEN"; message: string }
  | { type: "UNAVAILABLE"; message: string }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; connections: ManagedMultiConnection[] };

export interface MultiConnectionDetail {
  connection: ManagedMultiConnection;
  routes: ManagedMultiRoute[];
  defaults: ManagedChannelDefault[];
  routeOffset: number;
  defaultOffset: number;
  routeImpact: ExternalChannelMultiRouteImpact | null;
  connectionImpact: ExternalChannelMultiConnectionImpact | null;
}

export interface SlackManagementHandoffState {
  handoff: ManagedSlackManagementHandoff | null;
  message: string | null;
}
