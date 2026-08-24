import type { AgentRuntimeSystemMetricsResponse } from "@azents/public-client";

export type RuntimeSystemMetricsOverviewState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; metrics: AgentRuntimeSystemMetricsResponse };
