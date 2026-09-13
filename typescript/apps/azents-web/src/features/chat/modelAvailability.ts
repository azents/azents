import type { AgentSessionModelAvailabilityResponse } from "@azents/public-client";

export type ModelAvailabilityViewState =
  | { type: "UNAVAILABLE" }
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "LOADED"; data: AgentSessionModelAvailabilityResponse };

export type ModelAvailabilityBadge = "fallback" | "primary_next" | null;

export function modelAvailabilityBadge(
  state: ModelAvailabilityViewState,
  activeSemanticLabel: string,
): ModelAvailabilityBadge {
  if (
    state.type !== "LOADED" ||
    state.data.semantic_label !== activeSemanticLabel
  ) {
    return null;
  }
  if (state.data.state === "primary_next") {
    return "primary_next";
  }
  if (state.data.state === "cooldown" || state.data.state === "probing") {
    return "fallback";
  }
  return null;
}

export function modelAvailabilityRemainingMinutes(
  availability: AgentSessionModelAvailabilityResponse,
  observedAtMs: number,
  nowMs: number,
): number | null {
  if (availability.deadline == null) {
    return null;
  }
  const elapsedMs = Math.max(0, nowMs - observedAtMs);
  const remainingMs =
    Date.parse(availability.deadline) -
    Date.parse(availability.server_time) -
    elapsedMs;
  return remainingMs > 0 ? Math.ceil(remainingMs / 60_000) : null;
}
