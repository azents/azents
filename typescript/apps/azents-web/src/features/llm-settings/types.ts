/** LLM Provider Integration state type */

import type {
  LlmProviderIntegrationResponse,
  WorkspaceModelSettingsResponse,
} from "@azents/public-client";

/** Integration list state */
export type LlmIntegrationListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      integrations: LlmProviderIntegrationResponse[];
    };

export type WorkspaceModelSettingsState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      settings: WorkspaceModelSettingsResponse | null;
    };

/** Create/update form modal state */
export type FormModalState =
  | { type: "CLOSED" }
  | { type: "CREATE" }
  | { type: "EDIT"; integration: LlmProviderIntegrationResponse };

/** Mutation state */
export type MutationState =
  { type: "IDLE"; error: string | null } | { type: "SUBMITTING" };

export type ApiKeySecrets = { type: "api_key"; api_key: string };
export type AwsSecrets = {
  type: "aws_credentials";
  secret_access_key: string;
};
export type GcpSecrets = {
  type: "gcp_service_account";
  service_account_json: string;
};
export type ProviderSecrets = ApiKeySecrets | AwsSecrets | GcpSecrets;

export type AwsConfig = {
  type: "aws_credentials";
  access_key_id: string;
  region: string;
};
export type GcpConfig = {
  type: "gcp_service_account";
  project_id: string;
  region: string;
};
export type ProviderConfig = AwsConfig | GcpConfig;

export interface CreateIntegrationInput {
  provider: string;
  name?: string;
  secrets: ProviderSecrets;
  config?: ProviderConfig | null;
}

export interface UpdateIntegrationInput {
  name?: string;
  secrets?: ProviderSecrets;
  config?: ProviderConfig | null;
  enabled?: boolean;
}

/** Kimi device authorization state. */
export type KimiOAuthDeviceState =
  | { type: "IDLE" }
  | {
      type: "PENDING";
      sessionId: string;
      userCode: string;
      verificationUri: string;
      intervalMs: number;
      expiresAt: string;
    }
  | { type: "CONNECTED" }
  | { type: "ERROR"; message: string };
