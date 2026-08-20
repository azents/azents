import type {
  DiscordThreadAutoArchiveDurationMinutes,
  ExternalChannelResponseMode,
  ExternalChannelTransport,
  ManagedBlock,
  ManagedConnection,
  ManagedGrant,
  ManagedMultiConnection,
  SlackManifestGuidance,
} from "@azents/public-client";

export interface SlackCredentialDraft {
  botToken: string;
  signingSecret: string;
  appToken: string;
}

export type ConnectionDialogState =
  | {
      type: "SETUP";
      appId: string;
      transport: ExternalChannelTransport;
      credentials: SlackCredentialDraft;
    }
  | {
      type: "EDIT";
      connectionId: string;
      appId: string;
      transport: ExternalChannelTransport;
      credentials: SlackCredentialDraft;
    }
  | null;

export type DiscordConnectionDialogState =
  | {
      type: "SETUP";
      appId: string;
      targetGuildId: string;
      threadAutoArchiveDurationMinutes: DiscordThreadAutoArchiveDurationMinutes;
      botToken: string;
    }
  | {
      type: "EDIT";
      connectionId: string;
      appId: string;
      targetGuildId: string;
      threadAutoArchiveDurationMinutes: DiscordThreadAutoArchiveDurationMinutes;
      botToken: string;
    }
  | null;

export type ExternalChannelManagementState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      defaultResponseMode: ExternalChannelResponseMode;
      connections: ManagedConnection[];
      associatedMultiApps: ManagedMultiConnection[];
      grants: ManagedGrant[];
      blocks: ManagedBlock[];
    };

export type ManifestGuidanceState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; manifest: SlackManifestGuidance };
