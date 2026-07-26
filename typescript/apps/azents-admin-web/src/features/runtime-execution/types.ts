import type {
  RuntimeExecutionPlatformPolicyResponse,
  RuntimeExecutionPolicyAuditEventResponse,
  RuntimeExecutionPolicyDocument,
  RuntimeExecutionProfileResponse,
} from "@azents/admin-client";

export type RuntimeExecutionAdminState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      platform: RuntimeExecutionPlatformPolicyResponse;
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
  platformDraft: RuntimeExecutionPolicyDocument | null;
  profileDraft: RuntimeExecutionProfileDraft | null;
  selectedProfileId: string | null;
  profileModalOpened: boolean;
  savingPlatform: boolean;
  savingProfile: boolean;
  retiringProfile: boolean;
  actionError: string | null;
  onPlatformDraftChange: (policy: RuntimeExecutionPolicyDocument) => void;
  onSavePlatform: () => void;
  onSelectProfile: (profileId: string) => void;
  onProfileDraftChange: (draft: RuntimeExecutionProfileDraft) => void;
  onOpenCreateProfile: () => void;
  onCloseProfileModal: () => void;
  onSaveProfile: () => void;
  onRetireProfile: () => void;
}
