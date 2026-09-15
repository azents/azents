import type { AgentRuntimeCapability } from "@azents/public-client";

export type AgentTerminalSettingsContext =
  | {
      type: "CREATE";
      runtimeProfileId: string | null;
    }
  | {
      type: "EDIT";
      runtimeCapability: AgentRuntimeCapability;
    };

export function shouldShowAgentTerminalSettings(
  context: AgentTerminalSettingsContext,
): boolean {
  switch (context.type) {
    case "CREATE":
      return context.runtimeProfileId !== null;
    case "EDIT":
      return context.runtimeCapability === "managed";
  }
}
