import type { AgentModelSelection } from "@azents/public-client";

export function formatModelSelectionSummary(
  selection?: AgentModelSelection | null,
): string {
  if (selection == null) {
    return "Workspace default model";
  }
  return `${selection.provider} · ${selection.model_display_name}`;
}
