import type {
  RuntimeRecreationOperationResponse,
  SelectableInfrastructureProfileResponse,
  WorkspaceRuntimeProfileDefaultResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";

export type RuntimeProfilesState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      profiles: WorkspaceRuntimeProfileResponse[];
      infrastructureProfiles: SelectableInfrastructureProfileResponse[];
      defaultProfile: WorkspaceRuntimeProfileDefaultResponse;
    };

export type RuntimeProfileEditorState =
  | { type: "CLOSED" }
  | { type: "CREATE" }
  | { type: "EDIT"; profile: WorkspaceRuntimeProfileResponse };

export type RuntimeProfileMutationState =
  | { type: "IDLE"; error: string | null }
  | { type: "SUBMITTING" };

export type RuntimeProfileOperationState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; operation: RuntimeRecreationOperationResponse };
