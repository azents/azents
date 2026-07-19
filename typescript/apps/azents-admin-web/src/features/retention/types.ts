import type {
  ArchiveRetentionApplicationResponse,
  ArchiveRetentionPreviewResponse,
  FileLifecycleSettingsResponse,
} from "@azents/admin-client";

export type RetentionApplicationScope =
  | "new_archives_only"
  | "recalculate_existing";

export type RetentionSettingsState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; settings: FileLifecycleSettingsResponse };

export interface RetentionUpdateConfirmation {
  preview: ArchiveRetentionPreviewResponse;
  retentionDays: number | null;
}

export type RetentionApplicationState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; application: ArchiveRetentionApplicationResponse };
