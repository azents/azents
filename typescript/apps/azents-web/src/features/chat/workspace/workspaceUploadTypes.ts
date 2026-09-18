import type {
  WorkspaceUploadFailure,
  WorkspaceUploadPhase,
} from "@azents/public-client";

export type WorkspaceUploadUiPhase =
  | "queued"
  | "hashing"
  | "uploading"
  | "moving_to_runtime"
  | "succeeded"
  | "cancelled"
  | "conflicted"
  | "failed";

export type WorkspaceUploadRow = {
  id: string;
  filename: string;
  destinationPath: string;
  expectedSize: number;
  phase: WorkspaceUploadUiPhase;
  progress: number;
  transferredBytes: number;
  uploadId: string | null;
  revision: number | null;
  currentDeliveryNumber: number | null;
  failure: WorkspaceUploadFailure | null;
  errorMessage: string | null;
  retryAvailable: boolean;
  serverRetryAvailable: boolean;
  overwriteAvailable: boolean;
  conflictPrecondition: string | null;
};

export type WorkspaceUploadContainerOutput = {
  rows: WorkspaceUploadRow[];
  hasActiveUploads: boolean;
  uploadFiles: (files: FileList | File[], destinationDirectory: string) => void;
  cancelUpload: (id: string) => void;
  retryUpload: (id: string, overwrite: boolean) => void;
  dismissUpload: (id: string) => void;
};

export function isTerminalWorkspaceUploadPhase(
  phase: WorkspaceUploadPhase,
): boolean {
  return (
    phase === "succeeded" ||
    phase === "cancelled" ||
    phase === "conflicted" ||
    phase === "retryable_failure" ||
    phase === "failed" ||
    phase === "expired"
  );
}
