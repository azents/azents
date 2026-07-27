import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyAuditEventResponse,
  RuntimeExecutionPolicyDocument,
  RuntimeExecutionProfileResponse,
} from "@azents/admin-client";

export type RuntimeExecutionAdminState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      capabilities: RuntimeExecutionManagementCapabilitiesResponse;
      profiles: RuntimeExecutionProfileResponse[];
      auditEvents: RuntimeExecutionPolicyAuditEventResponse[];
    };

export interface RuntimeExecutionProfileDraft {
  id: string;
  displayName: string;
  description: string;
  policy: RuntimeExecutionPolicyDocument;
  expectedVersion: number | null;
  reserved: boolean;
}

export interface RuntimeExecutionPageContentProps {
  state: RuntimeExecutionAdminState;
  profileDraft: RuntimeExecutionProfileDraft | null;
  selectedProfileId: string | null;
  profileDetailOpen: boolean;
  profileModalOpened: boolean;
  savingProfile: boolean;
  retiringProfile: boolean;
  actionError: string | null;
  onSelectProfile: (profileId: string) => void;
  onProfileDetailClose: () => void;
  onProfileDraftChange: (draft: RuntimeExecutionProfileDraft) => void;
  onOpenCreateProfile: () => void;
  onCloseProfileModal: () => void;
  onSaveProfile: () => void;
  onRetireProfile: () => void;
}
