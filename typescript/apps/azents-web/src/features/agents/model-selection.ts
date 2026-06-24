import type {
  AgentModelSelection,
  AgentModelSelectionInput,
  LlmProviderIntegrationResponse,
  ModelCapabilities,
} from "@azents/public-client";

export interface SelectableModelCandidate {
  provider: string;
  model_identifier: string;
  model_display_name: string;
  normalized_capabilities: ModelCapabilities;
}

export interface ModelCatalogAttemptState {
  status: string;
  started_at: string;
  finished_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
  action_hint: string | null;
  fetched_count: number;
  matched_count: number;
  skipped_count: number;
  hidden_count: number;
}

export interface ModelCatalogState {
  catalogId: string;
  currentSnapshotId: string | null;
  currentSnapshotCreatedAt: string | null;
  latestAttempt: ModelCatalogAttemptState | null;
  total: number;
  loaded: number;
}

export interface ProviderIntegrationOption {
  value: string;
  label: string;
  provider: string;
  integration: LlmProviderIntegrationResponse;
  disabled: boolean;
}

export interface ModelSelectionOption {
  value: string;
  label: string;
  integrationId: string;
  integrationName: string;
  integrationEnabled: boolean;
  modelIdentifier: string;
  model: SelectableModelCandidate | AgentModelSelection;
  disabled: boolean;
}

export function modelSelectionValue(
  selection?: AgentModelSelectionInput | AgentModelSelection | null,
): string | null {
  if (selection == null) {
    return null;
  }
  return `${selection.llm_provider_integration_id}:${selection.model_identifier}`;
}

export function modelSelectionProviderValue(
  selection?: AgentModelSelectionInput | AgentModelSelection | null,
): string | null {
  if (selection == null) {
    return null;
  }
  return selection.llm_provider_integration_id;
}

export function parseModelSelectionValue(
  value: string | null,
): AgentModelSelectionInput | null {
  if (value == null) {
    return null;
  }
  const separatorIndex = value.indexOf(":");
  if (separatorIndex <= 0 || separatorIndex === value.length - 1) {
    return null;
  }
  return {
    llm_provider_integration_id: value.slice(0, separatorIndex),
    model_identifier: value.slice(separatorIndex + 1),
  };
}

export function formatModelSelectionSummary(
  selection?: AgentModelSelection | null,
): string {
  if (selection == null) {
    return "Workspace default model";
  }
  return `${selection.provider} · ${selection.model_display_name}`;
}

export function buildProviderIntegrationOptions(
  integrations: LlmProviderIntegrationResponse[],
): ProviderIntegrationOption[] {
  return integrations.map((integration) => ({
    value: integration.id,
    label: `${integration.name} · ${integration.provider}`,
    provider: integration.provider,
    integration,
    disabled: !integration.enabled,
  }));
}

export function buildModelSelectionOptions(
  integrations: LlmProviderIntegrationResponse[],
  modelsByIntegrationId: ReadonlyMap<string, SelectableModelCandidate[]>,
): ModelSelectionOption[] {
  return integrations.flatMap((integration) => {
    const models = modelsByIntegrationId.get(integration.id) ?? [];
    return models.map((model) => ({
      value: `${integration.id}:${model.model_identifier}`,
      label: `${model.model_display_name} (${model.model_identifier})`,
      integrationId: integration.id,
      integrationName: integration.name,
      integrationEnabled: integration.enabled,
      modelIdentifier: model.model_identifier,
      model,
      disabled: !integration.enabled,
    }));
  });
}

export function findModelSelectionOption(
  options: ModelSelectionOption[],
  value: string | null,
): ModelSelectionOption | null {
  if (value == null) {
    return null;
  }
  return options.find((option) => option.value === value) ?? null;
}
