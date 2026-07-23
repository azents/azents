import type { ChatMessage } from "./types";

export type ContinuationSource = "goal" | "external_channel";
export type ContinuationIcon = "target" | "channel";
export type ContinuationLabelKey =
  | "goalContinuationIndicator"
  | "externalChannelContinuationIndicator";

export interface ContinuationPresentation {
  source: ContinuationSource;
  icon: ContinuationIcon;
  labelKey: ContinuationLabelKey;
}

export function continuationMetadata(value: unknown): Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, item]) =>
      typeof item === "string" ? [[key, item]] : [],
    ),
  );
}

export function continuationPresentation(
  message?: ChatMessage | null,
): ContinuationPresentation {
  if (message?.metadata?.source === "external_channel") {
    return {
      source: "external_channel",
      icon: "channel",
      labelKey: "externalChannelContinuationIndicator",
    };
  }
  return {
    source: "goal",
    icon: "target",
    labelKey: "goalContinuationIndicator",
  };
}
