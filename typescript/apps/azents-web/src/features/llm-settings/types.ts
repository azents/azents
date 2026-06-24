/** LLM Provider Integration state type */

import type {
  LlmProviderIntegrationResponse,
  WorkspaceModelSettingsResponse,
} from "@azents/public-client";

/** Integration list state */
export type IntegrationListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      integrations: LlmProviderIntegrationResponse[];
      workspaceModelSettings: WorkspaceModelSettingsResponse | null;
    };

/** Create/update form modal state */
export type FormModalState =
  | { type: "CLOSED" }
  | { type: "CREATE" }
  | { type: "EDIT"; integration: LlmProviderIntegrationResponse };

/** Mutation state */
export type MutationState =
  | { type: "IDLE"; error: string | null }
  | { type: "SUBMITTING" };
