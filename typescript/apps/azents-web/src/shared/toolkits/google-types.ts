import type {
  GoogleConnectionOutput,
  GooglePreparation,
  GooglePublishedOutput,
  GoogleReview,
  GoogleService,
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
export type GooglePickerState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "OPEN" }
  | { type: "SELECTED"; count: number }
  | { type: "CANCELLED" }
  | { type: "ERROR"; message: string };
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
  services: GoogleService[];
  timeout: number;
  metadata: GoogleMetadata;
  publishingAllowed: boolean;
  reconnect: boolean;
  ownership: "user" | "workspace" | "agent";
  cancelling: boolean;
  disconnecting: boolean;
  savingServices: boolean;
  servicesDirty: boolean;
  picker: GooglePickerState;
  pickerAvailable: boolean;
  disconnectConfirmation: boolean;
  operationError: string | null;
  rootRef: RefObject<HTMLDivElement | null>;
  embedded: boolean;
  onServiceChange: (service: GoogleService, selected: boolean) => void;
  onSaveServices: () => Promise<void>;
  onOpenPicker: () => void;
  onClosePicker: () => void;
  onTimeoutChange: (value: number) => void;
  onMetadataChange: (patch: Partial<GoogleMetadata>) => void;
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
/** Publication requires usable actual evidence, not a requested-scope ceiling. */
export function canPublishGoogleReview(
  review: GoogleReview,
  services: GoogleService[],
  now: number,
): boolean {
  return (
    review.can_confirm &&
    review.renewable &&
    Date.parse(review.expires_at) > now &&
    services.length > 0 &&
    services.every((service) => review.services.includes(service)) &&
    review.accesses.some(
      (access) =>
        services.includes(access.service) && access.permitted_tools.length > 0,
    )
  );
}
