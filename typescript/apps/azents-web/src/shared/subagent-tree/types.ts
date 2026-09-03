import type { SubagentTreeResponse } from "@azents/public-client";

export type SubagentTreePanelState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; tree: SubagentTreeResponse };
