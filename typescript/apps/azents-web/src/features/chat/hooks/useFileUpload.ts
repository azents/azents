"use client";

/**
 * file upload hook.
 *
 * chat in file attachment and upload feature text.
 */

import { useCallback, useRef, useState } from "react";

/** upload complete file metadata */
export interface UploadedFile {
  attachmentId: string;
  uri: string;
  name: string;
  mediaType: string;
  size: number;
}

export type UploadErrorReason =
  | "fileTooLarge"
  | "invalidRequest"
  | "unauthorized"
  | "forbidden"
  | "unsupportedType"
  | "serverError"
  | "networkError"
  | "invalidResponse"
  | "unknown";

/** pending file */
export interface PendingFile {
  id: string;
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  errorReason?: UploadErrorReason;
  /** server insidetext detail etc. textfor text. */
  errorDetail?: string;
  /** user when sendwhen textwhenalsoto can exists textwhether whether. */
  errorRetryable?: boolean;
}

interface UseFileUploadReturn {
  pendingFiles: PendingFile[];
  addFiles: (files: FileList | File[]) => void;
  removeFile: (id: string) => void;
  clearFiles: () => void;
  resetDoneFiles: () => void;
  uploadAll: (agentId: string) => Promise<UploadedFile[]>;
  isUploading: boolean;
}

interface UploadResponse {
  attachment_id: string;
  uri: string;
  media_type: string;
  size: number;
  name?: string;
}

interface UploadFailureInfo {
  reason: UploadErrorReason;
  message: string;
  retryable: boolean;
  detail?: string;
}

const MAX_FILES = 5;
const MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024;

class UploadFailure extends Error {
  readonly reason: UploadErrorReason;
  readonly detail?: string;
  readonly retryable: boolean;

  constructor(info: UploadFailureInfo) {
    super(info.message);
    this.name = "UploadFailure";
    this.reason = info.reason;
    this.detail = info.detail;
    this.retryable = info.retryable;
  }
}

function getErrorBodyMessage(body: unknown): string | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  if ("detail" in body && typeof body.detail === "string") {
    return body.detail;
  }
  if ("error" in body && typeof body.error === "string") {
    return body.error;
  }
  return null;
}

function getUploadFailureInfo(
  status: number,
  body: unknown,
): UploadFailureInfo {
  const detail = getErrorBodyMessage(body);
  const suffix = detail ? ` ${detail}` : "";

  switch (status) {
    case 400:
      return {
        reason: "invalidRequest",
        message: `Upload failed: ${status}${suffix}`,
        retryable: false,
        ...(detail ? { detail } : {}),
      };
    case 401:
      return {
        reason: "unauthorized",
        message: `Upload failed: ${status}${suffix}`,
        retryable: true,
        ...(detail ? { detail } : {}),
      };
    case 403:
      return {
        reason: "forbidden",
        message: `Upload failed: ${status}${suffix}`,
        retryable: false,
        ...(detail ? { detail } : {}),
      };
    case 413:
      return {
        reason: "fileTooLarge",
        message: `Upload failed: ${status}${suffix}`,
        retryable: false,
        ...(detail ? { detail } : {}),
      };
    case 415:
      return {
        reason: "unsupportedType",
        message: `Upload failed: ${status}${suffix}`,
        retryable: false,
        ...(detail ? { detail } : {}),
      };
    default:
      return {
        reason: status >= 500 ? "serverError" : "unknown",
        message: `Upload failed: ${status}${suffix}`,
        retryable: status >= 500,
        ...(detail ? { detail } : {}),
      };
  }
}

function createFileTooLargeFailure(): UploadFailureInfo {
  return {
    reason: "fileTooLarge",
    message: "Upload failed: file size exceeds the 20 MB limit.",
    retryable: false,
    detail: "File size exceeds the 20 MB limit.",
  };
}

async function readUploadErrorBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function isUploadResponse(value: unknown): value is UploadResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "uri" in value &&
    typeof value.uri === "string" &&
    "attachment_id" in value &&
    typeof value.attachment_id === "string" &&
    "media_type" in value &&
    typeof value.media_type === "string" &&
    "size" in value &&
    typeof value.size === "number" &&
    (!("name" in value) || typeof value.name === "string")
  );
}

function getPendingFileUploadFailure(file: File): UploadFailureInfo | null {
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return createFileTooLargeFailure();
  }
  return null;
}

function toPendingFile(file: File): PendingFile {
  const failure = getPendingFileUploadFailure(file);
  return {
    id: `file-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    file,
    status: failure ? "error" : "pending",
    ...(failure
      ? {
          errorReason: failure.reason,
          errorRetryable: failure.retryable,
          ...(failure.detail ? { errorDetail: failure.detail } : {}),
        }
      : {}),
  };
}

function updatePendingFileStatus(
  pendingFile: PendingFile,
  status: PendingFile["status"],
): PendingFile {
  return {
    id: pendingFile.id,
    file: pendingFile.file,
    status,
  };
}

function shouldUpload(file: PendingFile): boolean {
  return file.status === "pending" || file.errorRetryable === true;
}

function getUploadFailure(error: unknown): UploadFailureInfo {
  if (error instanceof UploadFailure) {
    return {
      reason: error.reason,
      message: error.message,
      retryable: error.retryable,
      ...(error.detail ? { detail: error.detail } : {}),
    };
  }
  if (error instanceof TypeError) {
    return {
      reason: "networkError",
      message: "Upload failed: network error",
      retryable: true,
      detail: error.message,
    };
  }
  if (error instanceof Error) {
    return {
      reason: "unknown",
      message: error.message,
      retryable: true,
      detail: error.message,
    };
  }
  return {
    reason: "unknown",
    message: "Upload failed",
    retryable: true,
  };
}

export function useFileUpload(): UseFileUploadReturn {
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);

  const addFiles = useCallback((files: FileList | File[]) => {
    const fileArray = Array.from(files);
    setPendingFiles((prev) => {
      const remaining = MAX_FILES - prev.length;
      if (remaining <= 0) {
        return prev;
      }
      const newFiles = fileArray.slice(0, remaining).map(toPendingFile);
      return [...prev, ...newFiles];
    });
  }, []);

  const removeFile = useCallback((id: string) => {
    setPendingFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const clearFiles = useCallback(() => {
    setPendingFiles([]);
  }, []);

  /** send text when complete status text textwhenalso when when uploadto can existstext . */
  const resetDoneFiles = useCallback(() => {
    setPendingFiles((prev) =>
      prev.map((f) => (f.status === "done" ? { ...f, status: "pending" } : f)),
    );
  }, []);

  // pendingFiles ref with addtext uploadAll in latest status textalsotext .
  // useCallback of deps to pendingFiles textwhen file add wheneach
  // new docan createtext ChatView of handleSend not possiblerequiredtext textcreateis..
  const pendingFilesRef = useRef(pendingFiles);
  pendingFilesRef.current = pendingFiles;

  const uploadAll = useCallback(
    async (agentId: string): Promise<UploadedFile[]> => {
      const uploaded: UploadedFile[] = [];

      const currentFiles = pendingFilesRef.current.filter(shouldUpload);
      for (const pf of currentFiles) {
        setPendingFiles((prev) =>
          prev.map((f) =>
            f.id === pf.id ? updatePendingFileStatus(f, "uploading") : f,
          ),
        );

        try {
          const formData = new FormData();
          formData.append("file", pf.file);
          formData.append("agentId", agentId);

          const response = await fetch("/api/chat/upload", {
            method: "POST",
            body: formData,
          });

          if (!response.ok) {
            const errorBody = await readUploadErrorBody(response);
            throw new UploadFailure(
              getUploadFailureInfo(response.status, errorBody),
            );
          }

          const data: unknown = await response.json();
          if (!isUploadResponse(data)) {
            throw new UploadFailure({
              reason: "invalidResponse",
              message: "Invalid upload response",
              retryable: true,
            });
          }
          uploaded.push({
            attachmentId: data.attachment_id,
            uri: data.uri,
            name: data.name ?? pf.file.name,
            mediaType: data.media_type,
            size: data.size,
          });

          setPendingFiles((prev) =>
            prev.map((f) =>
              f.id === pf.id ? updatePendingFileStatus(f, "done") : f,
            ),
          );
        } catch (error) {
          const failure = getUploadFailure(error);
          setPendingFiles((prev) =>
            prev.map((f) =>
              f.id === pf.id
                ? {
                    ...updatePendingFileStatus(f, "error"),
                    errorReason: failure.reason,
                    errorRetryable: failure.retryable,
                    ...(failure.detail ? { errorDetail: failure.detail } : {}),
                  }
                : f,
            ),
          );
          throw error;
        }
      }

      return uploaded;
    },
    [],
  );

  const isUploading = pendingFiles.some((f) => f.status === "uploading");

  return {
    pendingFiles,
    addFiles,
    removeFile,
    clearFiles,
    resetDoneFiles,
    uploadAll,
    isUploading,
  };
}
