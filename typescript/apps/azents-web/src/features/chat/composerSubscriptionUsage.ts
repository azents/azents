import {
  subscriptionUsageSummaryLimits,
  supportsSubscriptionUsage,
} from "../llm-settings/subscriptionUsage.ts";
import type { SubscriptionUsageState } from "../llm-settings/subscriptionUsage.ts";
import type { AgentResponse } from "@azents/public-client";

export interface ComposerSubscriptionSelection {
  integrationId: string;
  provider: string;
}

export type ComposerSubscriptionIndicatorState =
  | { type: "HIDDEN" }
  | { type: "LOADING" }
  | {
      type: "PERCENT";
      label: string;
      percent: number;
      severity: "normal" | "warning" | "critical";
      stale: boolean;
    }
  | { type: "EXTERNAL"; stale: boolean }
  | { type: "UNAVAILABLE" };

export function resolveComposerSubscriptionSelection(
  options: AgentResponse["selectable_model_options"],
  modelTargetLabel: string,
): ComposerSubscriptionSelection | null {
  const selected = options.find((option) => option.label === modelTargetLabel);
  if (
    !selected ||
    !supportsSubscriptionUsage(selected.model_selection.provider)
  ) {
    return null;
  }
  return {
    integrationId: selected.model_selection.llm_provider_integration_id,
    provider: selected.model_selection.provider,
  };
}

export function composerSubscriptionSeverity(
  usedPercent: number,
): "normal" | "warning" | "critical" {
  if (usedPercent >= 90) {
    return "critical";
  }
  if (usedPercent >= 70) {
    return "warning";
  }
  return "normal";
}

export function projectComposerSubscriptionIndicator(
  state: SubscriptionUsageState,
): ComposerSubscriptionIndicatorState {
  switch (state.type) {
    case "IDLE":
    case "DISABLED":
      return { type: "HIDDEN" };
    case "LOADING":
      return { type: "LOADING" };
    case "AVAILABLE":
      return availableIndicator(state.snapshot, false);
    case "EXTERNAL":
      return { type: "EXTERNAL", stale: false };
    case "UNAVAILABLE":
      return { type: "UNAVAILABLE" };
    case "STALE_ERROR":
      if (state.snapshot.type === "external") {
        return { type: "EXTERNAL", stale: true };
      }
      return availableIndicator(state.snapshot, true);
  }
}

function availableIndicator(
  snapshot: Extract<SubscriptionUsageState, { type: "AVAILABLE" }>["snapshot"],
  stale: boolean,
): ComposerSubscriptionIndicatorState {
  const limit = subscriptionUsageSummaryLimits(snapshot).at(0);
  if (!limit) {
    return { type: "UNAVAILABLE" };
  }
  const percent = Math.min(100, Math.max(0, limit.used_percent));
  return {
    type: "PERCENT",
    label: limit.label,
    percent,
    severity: composerSubscriptionSeverity(percent),
    stale,
  };
}
