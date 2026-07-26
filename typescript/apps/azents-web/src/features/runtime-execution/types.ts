import type {
  AgentResponse,
  AgentRuntimeExecutionPolicyResponse,
  AgentRuntimeExecutionPolicyStatusResponse,
  RuntimeExecutionPolicyAuditEventResponse,
  RuntimeExecutionPolicyRestriction,
  WorkspaceRuntimeExecutionPolicyResponse,
  WorkspaceRuntimeExecutionProfileResponse,
} from "@azents/public-client";

export type WorkspaceRuntimeExecutionState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      policy: WorkspaceRuntimeExecutionPolicyResponse;
      profiles: WorkspaceRuntimeExecutionProfileResponse[];
      auditEvents: RuntimeExecutionPolicyAuditEventResponse[];
      canEdit: boolean;
    };

export interface WorkspaceRuntimeExecutionProps {
  state: WorkspaceRuntimeExecutionState;
  restriction: RuntimeExecutionPolicyRestriction | null;
  allowedProfileIds: string[];
  saving: boolean;
  canSave: boolean;
  hasUnsupportedSelection: boolean;
  actionError: string | null;
  onRestrictionChange: (restriction: RuntimeExecutionPolicyRestriction) => void;
  onToggleProfile: (profileId: string, allowed: boolean) => void;
  onSave: () => void;
}

export type AgentRuntimeStatusState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; status: AgentRuntimeExecutionPolicyStatusResponse };

export type AgentRuntimeExecutionState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      policy: AgentRuntimeExecutionPolicyResponse;
      profiles: WorkspaceRuntimeExecutionProfileResponse[];
      auditEvents: RuntimeExecutionPolicyAuditEventResponse[];
    };

export interface AgentRuntimeExecutionProps {
  handle: string;
  agent: AgentResponse;
  state: AgentRuntimeExecutionState;
  statusState: AgentRuntimeStatusState;
  profileId: string | null;
  restriction: RuntimeExecutionPolicyRestriction | null;
  saving: boolean;
  applying: boolean;
  canSave: boolean;
  actionError: string | null;
  actionMessage: "saved" | "applied" | null;
  onProfileChange: (profileId: string) => void;
  onRestrictionChange: (restriction: RuntimeExecutionPolicyRestriction) => void;
  onSave: () => void;
  onApply: () => void;
}
