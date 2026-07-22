import type {
  ExternalChannelDecisionInput,
  ManagedApprovalRequest,
} from "@azents/public-client";

export type ExternalChannelApprovalDecision =
  ExternalChannelDecisionInput["decision"];

export type ExternalChannelApprovalActionError = "CONFLICT" | "ERROR";

export type ExternalChannelApprovalState =
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | { type: "UNAUTHORIZED" }
  | { type: "ERROR" }
  | {
      type: "READY";
      request: ManagedApprovalRequest;
      submittingDecision: ExternalChannelApprovalDecision | null;
      actionError: ExternalChannelApprovalActionError | null;
    };
