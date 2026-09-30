import type {
  AgentResponse,
  ModelExecutionOptionDefinition,
  ModelExecutionOptionId,
  RequestedInferenceProfile,
} from "@azents/public-client";

export type ChatExecutionOptionDefinition = ModelExecutionOptionDefinition;

export interface ChatExecutionOptionGroup {
  id: string;
  definitions: ChatExecutionOptionDefinition[];
}

type SelectableModelOption = AgentResponse["selectable_model_options"][number];

export function isExecutionOptionId(
  value: unknown,
): value is ModelExecutionOptionId {
  return value === "fast" || value === "ultrafast";
}

/** Keep unknown or malformed live provenance distinct from ordinary intent. */
export function executionOptionIdsFromValue(
  value: unknown,
): ModelExecutionOptionId[] | null {
  if (!Array.isArray(value) || !value.every(isExecutionOptionId)) {
    return null;
  }
  return new Set(value).size === value.length ? value : null;
}

export function executionOptionGroups(
  definitions: readonly ChatExecutionOptionDefinition[],
): ChatExecutionOptionGroup[] {
  const groups = new Map<string, ChatExecutionOptionDefinition[]>();
  for (const definition of definitions) {
    if (definition.exclusive_group === null) {
      continue;
    }
    const members = groups.get(definition.exclusive_group) ?? [];
    members.push(definition);
    groups.set(definition.exclusive_group, members);
  }
  return [...groups].map(([id, members]) => ({ id, definitions: members }));
}

/** Empty selection clears only this registry group, retaining other intent. */
export function selectExecutionOptionInGroup(
  profile: RequestedInferenceProfile,
  definitions: readonly ChatExecutionOptionDefinition[],
  groupId: string,
  selectedId: string,
): RequestedInferenceProfile {
  const members = definitions.filter(
    (definition) => definition.exclusive_group === groupId,
  );
  const selected = members.find((definition) => definition.id === selectedId);
  if (members.length === 0 || (selectedId !== "" && selected === void 0)) {
    return profile;
  }
  const memberIds = new Set(members.map((definition) => definition.id));
  return {
    ...profile,
    enabled_execution_options: [
      ...profile.enabled_execution_options.filter((id) => !memberIds.has(id)),
      ...(selected === void 0 ? [] : [selected.id]),
    ],
  };
}

/** Prepared intent, not the provider's verified served tier. */
export function processingSpeedIntent(
  profile: Pick<RequestedInferenceProfile, "enabled_execution_options"> | null,
): "normal" | "fast" | "ultrafast" | null {
  if (profile === null) {
    return null;
  }
  const speedIds =
    profile.enabled_execution_options.filter(isExecutionOptionId);
  if (speedIds.length > 1) {
    return null;
  }
  return speedIds[0] ?? "normal";
}

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
