import type {
  AgentModelSelection,
  AgentModelSelectionInput,
  ImageGenerationModelCatalogResponse,
  LlmProviderIntegrationResponse,
  ModelCapabilities,
  SelectableModelOption,
  SelectableModelOptionInput,
} from "@azents/public-client";

export const MAX_SELECTABLE_MODEL_OPTIONS = 10;
export const MAX_SELECTABLE_MODEL_CANDIDATES = 5;
export const MAX_SUBAGENT_GUIDANCE_LENGTH = 500;

export function isSubagentGuidanceWithinLimit(
  guidance: string | null,
): boolean {
  return guidance == null || guidance.length <= MAX_SUBAGENT_GUIDANCE_LENGTH;
}

export interface SelectableModelCandidate {
  provider: string;
  model_identifier: string;
  model_display_name: string;
  normalized_capabilities: ModelCapabilities;
}

export interface ModelContextRange {
  defaultInputTokens: number | null;
  maxInputTokens: number | null;
}

export type ModelContextBadgeValue =
  | { type: "SINGLE"; tokens: number }
  | { type: "RANGE"; defaultTokens: number; maxTokens: number }
  | null;

export function resolveModelContextRange(
  contextWindow?: ModelCapabilities["context_window"] | null,
): ModelContextRange {
  const maxInputTokens = contextWindow?.max_input_tokens ?? null;
  const advertisedDefaultInputTokens =
    contextWindow?.default_input_tokens ?? maxInputTokens;
  return {
    defaultInputTokens:
      advertisedDefaultInputTokens == null || maxInputTokens == null
        ? advertisedDefaultInputTokens
        : Math.min(advertisedDefaultInputTokens, maxInputTokens),
    maxInputTokens,
  };
}

export function modelContextBadgeValue(
  contextWindow?: ModelCapabilities["context_window"] | null,
): ModelContextBadgeValue {
  const context = resolveModelContextRange(contextWindow);
  if (context.defaultInputTokens == null) {
    return null;
  }
  if (
    context.maxInputTokens != null &&
    context.defaultInputTokens !== context.maxInputTokens
  ) {
    return {
      type: "RANGE",
      defaultTokens: Math.round(context.defaultInputTokens / 1000),
      maxTokens: Math.round(context.maxInputTokens / 1000),
    };
  }
  return {
    type: "SINGLE",
    tokens: Math.round(context.defaultInputTokens / 1000),
  };
}

export interface SelectableModelCandidateFormValue {
  id: string;
  model_provider_integration_id: string | null;
  model_selection_value: string | null;
  model_display_name: string | null;
  model_identifier: string | null;
  normalized_capabilities: ModelCapabilities | null;
  context_window_tokens: number | null;
  max_output_tokens: number | null;
  builtin_tools: string[];
  builtin_tool_configs: Record<string, Record<string, unknown>>;
}

export interface SelectableModelOptionFormValue {
  id: string;
  label: string;
  candidates: SelectableModelCandidateFormValue[];
  subagent_enabled: boolean;
  subagent_guidance: string | null;
}

export interface PrimarySettingsCopyResult {
  candidate: SelectableModelCandidateFormValue;
  omitted: Array<"context_window" | "max_output" | "builtin_tools">;
}

export function copyCompatiblePrimarySettings(
  primary: SelectableModelCandidateFormValue,
  target: SelectableModelCandidateFormValue,
): PrimarySettingsCopyResult {
  const omitted: PrimarySettingsCopyResult["omitted"] = [];
  const targetContext = target.normalized_capabilities?.context_window;
  const contextWindowTokens =
    primary.context_window_tokens == null ||
    targetContext?.max_input_tokens == null ||
    primary.context_window_tokens <= targetContext.max_input_tokens
      ? primary.context_window_tokens
      : null;
  if (
    primary.context_window_tokens != null &&
    contextWindowTokens !== primary.context_window_tokens
  ) {
    omitted.push("context_window");
  }
  const maxOutputTokens =
    primary.max_output_tokens == null ||
    targetContext?.max_output_tokens == null ||
    primary.max_output_tokens <= targetContext.max_output_tokens
      ? primary.max_output_tokens
      : null;
  if (
    primary.max_output_tokens != null &&
    maxOutputTokens !== primary.max_output_tokens
  ) {
    omitted.push("max_output");
  }
  const supportedTools =
    target.normalized_capabilities?.built_in_tools?.supported ?? [];
  const builtinTools = primary.builtin_tools.filter((tool) =>
    supportedTools.includes(tool),
  );
  if (builtinTools.length !== primary.builtin_tools.length) {
    omitted.push("builtin_tools");
  }
  return {
    candidate: {
      ...target,
      context_window_tokens: contextWindowTokens,
      max_output_tokens: maxOutputTokens,
      builtin_tools: builtinTools,
      builtin_tool_configs: Object.fromEntries(
        builtinTools.map((tool) => [
          tool,
          { ...(primary.builtin_tool_configs[tool] ?? {}) },
        ]),
      ),
    },
    omitted,
  };
}

export function createSelectableModelCandidateFormValue(
  id: string,
): SelectableModelCandidateFormValue {
  return {
    id,
    model_provider_integration_id: null,
    model_selection_value: null,
    model_display_name: null,
    model_identifier: null,
    normalized_capabilities: null,
    context_window_tokens: null,
    max_output_tokens: null,
    builtin_tools: [],
    builtin_tool_configs: {},
  };
}

export function createSelectableModelOptionFormValue(
  id: string,
): SelectableModelOptionFormValue {
  return {
    id,
    label: "",
    candidates: [createSelectableModelCandidateFormValue(`${id}-candidate-1`)],
    subagent_enabled: true,
    subagent_guidance: null,
  };
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
  catalogScope: "system" | "integration";
  currentSnapshotId: string | null;
  currentSnapshotCreatedAt: string | null;
  latestAttempt: ModelCatalogAttemptState | null;
  stale: boolean;
  syncAvailableAt: string | null;
  automaticRetryBlocked: boolean;
  total: number;
  loaded: number;
}

export type ImageGenerationCatalogState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "UNSUPPORTED"; data: ImageGenerationModelCatalogResponse }
  | { type: "LOADED"; data: ImageGenerationModelCatalogResponse };

export type ImageGenerationModelAvailability =
  "AVAILABLE" | "UNAVAILABLE" | "UNVERIFIED";

export function imageGenerationModelSelectionVisible(
  state: ImageGenerationCatalogState | null,
): boolean {
  return state?.type !== "UNSUPPORTED";
}

export function imageGenerationModelIdentifier(
  candidate: SelectableModelCandidateFormValue,
): string | null {
  const model = candidate.builtin_tool_configs.image_generation?.model;
  return typeof model === "string" && model.trim().length > 0 ? model : null;
}

export function withImageGenerationModelIdentifier(
  candidate: SelectableModelCandidateFormValue,
  modelIdentifier: string | null,
): SelectableModelCandidateFormValue {
  const imageGenerationConfig = {
    ...(candidate.builtin_tool_configs.image_generation ?? {}),
  };
  if (modelIdentifier == null) {
    delete imageGenerationConfig.model;
  } else {
    imageGenerationConfig.model = modelIdentifier;
  }
  return {
    ...candidate,
    builtin_tool_configs: {
      ...candidate.builtin_tool_configs,
      image_generation: imageGenerationConfig,
    },
  };
}

export function imageGenerationModelAvailability(
  modelIdentifier: string,
  state: ImageGenerationCatalogState | null,
): ImageGenerationModelAvailability {
  if (state == null || state.type === "LOADING" || state.type === "ERROR") {
    return "UNVERIFIED";
  }
  if (state.type === "UNSUPPORTED") {
    return "UNAVAILABLE";
  }
  if (!state.data.generation_current || state.data.snapshot_id == null) {
    return "UNVERIFIED";
  }
  return state.data.entries.some(
    (entry) => entry.provider_model_identifier === modelIdentifier,
  )
    ? "AVAILABLE"
    : "UNAVAILABLE";
}

export function hasInvalidImageGenerationSelections(
  options: SelectableModelOptionFormValue[],
  states: ReadonlyMap<string, ImageGenerationCatalogState>,
): boolean {
  return options.some((option) =>
    option.candidates.some((candidate) => {
      if (!candidate.builtin_tools.includes("image_generation")) {
        return false;
      }
      const integrationId = candidate.model_provider_integration_id;
      const state =
        integrationId == null ? null : (states.get(integrationId) ?? null);
      if (
        (state?.type === "LOADED" || state?.type === "UNSUPPORTED") &&
        !state.data.default_available
      ) {
        return true;
      }
      const modelIdentifier = imageGenerationModelIdentifier(candidate);
      if (modelIdentifier == null) {
        return false;
      }
      return (
        integrationId == null ||
        imageGenerationModelAvailability(modelIdentifier, state) !== "AVAILABLE"
      );
    }),
  );
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
    candidates: option.candidates.map((candidate, candidateIndex) => ({
      id: `stored-${index}-${candidateIndex}-${option.label}`,
      model_provider_integration_id:
        candidate.model_selection.llm_provider_integration_id,
      model_selection_value: modelSelectionValue(candidate.model_selection),
      model_display_name: candidate.model_selection.model_display_name,
      model_identifier: candidate.model_selection.model_identifier,
      normalized_capabilities:
        candidate.model_selection.normalized_capabilities,
      context_window_tokens: candidate.settings.context_window_tokens,
      max_output_tokens: candidate.settings.max_output_tokens,
      builtin_tools: candidate.settings.builtin_tools.map((tool) => tool.name),
      builtin_tool_configs: Object.fromEntries(
        candidate.settings.builtin_tools.map((tool) => [
          tool.name,
          tool.config ?? {},
        ]),
      ),
    })),
    subagent_enabled: option.subagent_enabled,
    subagent_guidance: option.subagent_guidance,
  };
}

export function selectableModelOptionFormValuesFromStoredOptions(
  options: SelectableModelOption[],
): SelectableModelOptionFormValue[] {
  return options.map((option, index) =>
    selectableModelOptionFormValueFromStoredOption(option, index),
  );
}

export function hasDuplicateSelectableModelCandidates(
  options: SelectableModelOptionFormValue[],
): boolean {
  return options.some((option) => {
    const identities = new Set<string>();
    return option.candidates.some((candidate) => {
      const identity = candidate.model_selection_value;
      if (identity == null) {
        return false;
      }
      if (identities.has(identity)) {
        return true;
      }
      identities.add(identity);
      return false;
    });
  });
}

export function selectableModelOptionInputsFromFormValues(
  options: SelectableModelOptionFormValue[],
): SelectableModelOptionInput[] {
  return options.flatMap((option) => {
    const label = option.label.trim();
    const candidates = option.candidates.flatMap((candidate) => {
      const modelSelection = parseModelSelectionValue(
        candidate.model_selection_value,
      );
      if (modelSelection == null) {
        return [];
      }
      return [
        {
          model_selection: modelSelection,
          settings: {
            context_window_tokens: candidate.context_window_tokens,
            max_output_tokens: candidate.max_output_tokens,
            builtin_tools: candidate.builtin_tools.map((name) => ({
              name,
              config: candidate.builtin_tool_configs[name] ?? {},
            })),
          },
        },
      ];
    });
    if (candidates.length !== option.candidates.length || label.length === 0) {
      return [];
    }
    return [
      {
        label,
        candidates,
        subagent_enabled: option.subagent_enabled,
        subagent_guidance: option.subagent_guidance?.trim() || null,
      },
    ];
  });
}

export function fallbackSelectableModelLabel(
  label: string | null,
  options: SelectableModelOptionFormValue[],
): string | null {
  const trimmed = label?.trim() ?? "";
  if (
    trimmed.length > 0 &&
    options.some((option) => option.label.trim() === trimmed)
  ) {
    return trimmed;
  }
  return (
    options
      .map((option) => option.label.trim())
      .find((optionLabel) => optionLabel.length > 0) ?? null
  );
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
