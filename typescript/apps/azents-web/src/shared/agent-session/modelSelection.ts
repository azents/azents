import type {
  AgentModelSelection,
  AgentResponse,
  SelectableModelOptionResponse,
} from "@azents/public-client";

export function primaryModelSelection(
  option: SelectableModelOptionResponse,
): AgentModelSelection | null {
  return option.candidates[0]?.model_selection ?? null;
}

export function agentPrimaryModelSelection(
  agent: AgentResponse,
): AgentModelSelection | null {
  const option =
    agent.selectable_model_options.find(
      (candidate) => candidate.label === agent.main_model_label,
    ) ?? agent.selectable_model_options[0];
  return option == null ? null : primaryModelSelection(option);
}
