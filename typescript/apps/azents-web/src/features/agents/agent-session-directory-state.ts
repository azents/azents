import type { AgentSessionResponse } from "@azents/public-client";

export interface AgentSessionDirectorySnapshot {
  sessions: AgentSessionResponse[];
  totalCount: number;
  currentArchiveRetentionDays: number | null;
}

export type AgentSessionDirectoryQueryState =
  | {
      type: "LOADING";
      snapshot: AgentSessionDirectorySnapshot;
      message: string | null;
    }
  | {
      type: "ERROR";
      snapshot: AgentSessionDirectorySnapshot;
      message: string;
    }
  | { type: "LOADED"; snapshot: AgentSessionDirectorySnapshot };

/** Retain stale summary data while making the query's rendering phase explicit. */
export function projectAgentSessionDirectoryQueryState(
  snapshot: AgentSessionDirectorySnapshot,
  pending: boolean,
  error: string | null,
): AgentSessionDirectoryQueryState {
  if (pending) {
    return { type: "LOADING", snapshot, message: error };
  }
  if (error) {
    return { type: "ERROR", snapshot, message: error };
  }
  return { type: "LOADED", snapshot };
}
