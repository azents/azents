import type {
  AgentModelSelection,
  AgentModelSelectionInput,
  LlmProviderIntegrationResponse,
  ModelCapabilities,
  SelectableModelOption,
  SelectableModelOptionInput,
} from "@azents/public-client";

export const MAX_SELECTABLE_MODEL_OPTIONS = 10;

export interface SelectableModelCandidate {
  provider: string;
  model_identifier: string;
  model_display_name: string;
  normalized_capabilities: ModelCapabilities;
}

export interface SelectableModelOptionFormValue {
  id: string;
  label: string;
  model_provider_integration_id: string | null;
  model_selection_value: string | null;
  model_display_name: string | null;
  model_identifier: string | null;
  normalized_capabilities: ModelCapabilities | null;
  context_window_tokens: number | null;
  max_output_tokens: number | null;
  builtin_tools: string[];
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

export function selectableModelOptionFormValueFromStoredOption(
  option: SelectableModelOption,
  index: number,
): SelectableModelOptionFormValue {
  return {
    id: `stored-${index}-${option.label}`,
    label: option.label,
    model_provider_integration_id:
      option.model_selection.llm_provider_integration_id,
    model_selection_value: modelSelectionValue(option.model_selection),
    model_display_name: option.model_selection.model_display_name,
    model_identifier: option.model_selection.model_identifier,
    normalized_capabilities: option.model_selection.normalized_capabilities,
    context_window_tokens: option.settings.context_window_tokens,
    max_output_tokens: option.settings.max_output_tokens,
    builtin_tools: option.settings.builtin_tools.map((tool) => tool.name),
  };
}

export function selectableModelOptionFormValuesFromStoredOptions(
  options: SelectableModelOption[],
): SelectableModelOptionFormValue[] {
  return options.map((option, index) =>
    selectableModelOptionFormValueFromStoredOption(option, index),
  );
}

export function selectableModelOptionInputsFromFormValues(
  options: SelectableModelOptionFormValue[],
): SelectableModelOptionInput[] {
  return options.flatMap((option) => {
    const modelSelection = parseModelSelectionValue(
      option.model_selection_value,
    );
    const label = option.label.trim();
    if (modelSelection == null || label.length === 0) {
      return [];
    }
    return [
      {
        label,
        model_selection: modelSelection,
        settings: {
          context_window_tokens: option.context_window_tokens,
          max_output_tokens: option.max_output_tokens,
          builtin_tools: option.builtin_tools.map((name) => ({ name })),
        },
      },
    ];
  });
}

export function fallbackSelectableModelLabel(
  label: string | null,
  options: SelectableModelOptionFormValue[],
): string | null {
  const firstLabel = options[0]?.label.trim() ?? null;
  if (firstLabel == null || firstLabel.length === 0) {
    return null;
  }
  if (label == null) {
    return firstLabel;
  }
  const trimmed = label.trim();
  if (options.some((option) => option.label.trim() === trimmed)) {
    return trimmed;
  }
  return firstLabel;
}

export function findSelectableModelOptionByLabel(
  options: SelectableModelOptionFormValue[],
  label: string | null,
): SelectableModelOptionFormValue | null {
  const effectiveLabel = fallbackSelectableModelLabel(label, options);
  if (effectiveLabel == null) {
    return null;
  }
  return (
    options.find((option) => option.label.trim() === effectiveLabel) ?? null
  );
}

export function selectableModelLabelSelectData(
  options: SelectableModelOptionFormValue[],
): Array<{ value: string; label: string }> {
  return options.flatMap((option) => {
    const label = option.label.trim();
    if (label.length === 0) {
      return [];
    }
    return [{ value: label, label }];
  });
}
