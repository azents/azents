import type {
  RuntimeRecreationOperationResponse,
  SelectableInfrastructureProfileResponse,
  WorkspaceRuntimeProfileDefaultResponse,
  WorkspaceRuntimeProfileDeleteResponse,
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
  { type: "IDLE"; error: string | null } | { type: "SUBMITTING" };

export type RuntimeProfileOperationState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; operation: RuntimeRecreationOperationResponse };

export type RuntimeProfileDeletionErrorKind =
  | "CONFLICT"
  | "NOT_FOUND"
  | "FORBIDDEN"
  | "UNAUTHORIZED"
  | "BAD_REQUEST"
  | "UNKNOWN";

export type RuntimeProfileDeletionState =
  | { type: "CLOSED" }
  | {
      type: "CONFIRMING";
      profile: WorkspaceRuntimeProfileResponse;
      error: {
        kind: RuntimeProfileDeletionErrorKind;
        message: string;
      } | null;
    }
  | {
      type: "SUBMITTING";
      profile: WorkspaceRuntimeProfileResponse;
    };

export type RuntimeProfileDeletionFeedbackState =
  | { type: "NONE" }
  | {
      type: "SUCCESS";
      profileName: string;
      result: WorkspaceRuntimeProfileDeleteResponse;
    };
