import type {
  ExternalChannelTransport,
  ManagedBlock,
  ManagedConnection,
  ManagedGrant,
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
      type: "RECONNECT";
      connectionId: string;
      transport: ExternalChannelTransport;
      credentials: SlackCredentialDraft;
    }
  | null;

export type ExternalChannelManagementState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      connections: ManagedConnection[];
      grants: ManagedGrant[];
      blocks: ManagedBlock[];
    };

export type ManifestGuidanceState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; manifest: SlackManifestGuidance };
