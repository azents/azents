import type {
  GoogleConnectionOutput,
  GooglePreparation,
  GooglePublishedOutput,
  GoogleReview,
  GoogleTask,
} from "@azents/public-client";
import type { RefObject } from "react";

export type GooglePreparationState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; detail: GooglePreparation };
export type GoogleSavedState =
  | { type: "NEW" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; detail: GoogleConnectionOutput };
export type GoogleFlowState =
  | { type: "SELECT" }
  | { type: "AUTHORIZING" }
  | { type: "VERIFYING" }
  | { type: "REVIEW"; review: GoogleReview }
  | { type: "CONFIRMING"; review: GoogleReview }
  | { type: "UNKNOWN"; checking: boolean; message: string | null }
  | { type: "ERROR"; message: string }
  | { type: "COMPLETE"; outcome: GooglePublishedOutput };
export interface GoogleMetadata {
  name: string;
  slug: string;
  description: string;
  prompt: string;
  enabled: boolean;
  alwaysExposeTools: boolean;
}
export interface GoogleSetupProps {
  preparation: GooglePreparationState;
  saved: GoogleSavedState;
  flow: GoogleFlowState;
  tasks: GoogleTask[];
  timeout: number;
  metadata: GoogleMetadata;
  acknowledged: boolean;
  publishingAllowed: boolean;
  reconnect: boolean;
  ownership: "user" | "workspace" | "agent";
  cancelling: boolean;
  disconnecting: boolean;
  disconnectConfirmation: boolean;
  operationError: string | null;
  rootRef: RefObject<HTMLDivElement | null>;
  embedded: boolean;
  onTaskChange: (task: GoogleTask, selected: boolean) => void;
  onTimeoutChange: (value: number) => void;
  onMetadataChange: (patch: Partial<GoogleMetadata>) => void;
  onAcknowledgedChange: (value: boolean) => void;
  onAuthorize: () => void;
  onPublish: () => void;
  onCheckOutcome: () => void;
  onCancel: () => void;
  onRestart: () => void;
  onRefresh: () => void;
  onAskDisconnect: () => void;
  onDismissDisconnect: () => void;
  onDisconnect: () => void;
}
/** Selected tasks and actual tool evidence, never requested scopes, admit publication. */
export function canPublishGoogleReview(
  review: GoogleReview,
  tasks: GoogleTask[],
  acknowledged: boolean,
  now: number,
): boolean {
  return (
    acknowledged &&
    review.can_confirm &&
    review.renewable &&
    Date.parse(review.expires_at) > now &&
    tasks.length > 0 &&
    tasks.every((task) => review.requested_tasks.includes(task)) &&
    review.tasks.some(
      (access) =>
        tasks.includes(access.task) && access.permitted_tools.length > 0,
    )
  );
}
