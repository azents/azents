import type {
  AgentResponse,
  ModelExecutionOptionDefinition,
  ModelExecutionOptionId,
  RequestedInferenceProfile,
} from "@azents/public-client";

export type ChatExecutionOptionDefinition = ModelExecutionOptionDefinition;

type SelectableModelOption = AgentResponse["selectable_model_options"][number];

export function executionOptionDefinitionsForModel(
  option: SelectableModelOption,
): ChatExecutionOptionDefinition[] {
  return option.execution_option_definitions;
}

export function supportedExecutionOptionIds(
  option?: SelectableModelOption | null,
): ModelExecutionOptionId[] {
  return (
    option?.candidates[0]?.model_selection.supported_execution_options ?? []
  );
}

export function enabledExecutionOptionIds(
  profile?: RequestedInferenceProfile | null,
): ModelExecutionOptionId[] {
  return profile?.enabled_execution_options ?? [];
}

export function normalizeEnabledExecutionOptions(
  profile: RequestedInferenceProfile,
  supportedIds: readonly ModelExecutionOptionId[],
): ModelExecutionOptionId[] {
  const supported = new Set(supportedIds);
  return enabledExecutionOptionIds(profile).filter((id) => supported.has(id));
}

export function normalizeComposerProfile(
  profile: RequestedInferenceProfile,
  supportedIds: readonly ModelExecutionOptionId[],
): RequestedInferenceProfile {
  return {
    model_target_label: profile.model_target_label,
    reasoning_effort: profile.reasoning_effort,
    enabled_execution_options: normalizeEnabledExecutionOptions(
      profile,
      supportedIds,
    ),
  };
}
