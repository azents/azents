import type {
  AgentSessionResponse,
  ManagedBinding,
  ManagedGrant,
} from "@azents/public-client";

export type SessionChannelsState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      session: AgentSessionResponse;
      bindings: ManagedBinding[];
      grants: ManagedGrant[];
    };
