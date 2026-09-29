"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BrowserFileUploadHttpError,
  BrowserFileUploadInvalidResponseError,
  type BrowserFileUploadTask,
  isFileUploadSizeAllowed,
  startBrowserFileUpload,
} from "./browserFileUpload";
import {
  createFileUploadCancellationCoordinator,
  type FileUploadCancellationCoordinator,
} from "./fileUploadCancellation";

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

export interface PendingFile {
  id: string;
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  errorReason?: UploadErrorReason;
  errorDetail?: string;
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

interface UploadFailureInfo {
  reason: UploadErrorReason;
  message: string;
  retryable: boolean;
  detail?: string;
}

interface UploadOperation {
  task: BrowserFileUploadTask | null;
  cancelled: boolean;
}

const MAX_FILES = 5;

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
    message: "Upload failed: file size exceeds the 128 MiB limit.",
    retryable: false,
    detail: "File size exceeds the 128 MiB limit.",
  };
}

function getPendingFileUploadFailure(file: File): UploadFailureInfo | null {
  if (!isFileUploadSizeAllowed(file.size)) {
    return createFileTooLargeFailure();
  }
  return null;
}

function toPendingFile(file: File): PendingFile {
  const failure = getPendingFileUploadFailure(file);
  return {
    id: `file-${globalThis.crypto.randomUUID()}`,
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
  if (error instanceof BrowserFileUploadHttpError) {
    return getUploadFailureInfo(error.status, error.body);
  }
  if (error instanceof BrowserFileUploadInvalidResponseError) {
    return {
      reason: "invalidResponse",
      message: error.message,
      retryable: true,
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

function cancelUploadOperation(operation: UploadOperation): void {
  operation.cancelled = true;
  operation.task?.cancel();
}

export function useFileUpload(): UseFileUploadReturn {
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const pendingFilesRef = useRef<PendingFile[]>([]);
  const cancellationRef =
    useRef<FileUploadCancellationCoordinator<UploadOperation> | null>(null);
  if (cancellationRef.current === null) {
    cancellationRef.current = createFileUploadCancellationCoordinator(
      cancelUploadOperation,
    );
  }

  const updatePendingFiles = useCallback(
    (update: (files: PendingFile[]) => PendingFile[]): void => {
      setPendingFiles((previous) => {
        const next = update(previous);
        pendingFilesRef.current = next;
        return next;
      });
    },
    [],
  );

  const cancelFile = useCallback((id: string): void => {
    cancellationRef.current?.cancelFile(id);
  }, []);

  const addFiles = useCallback(
    (files: FileList | File[]): void => {
      const fileArray = Array.from(files);
      updatePendingFiles((previous) => {
        const remaining = MAX_FILES - previous.length;
        if (remaining <= 0) {
          return previous;
        }
        const nextFiles = fileArray.slice(0, remaining).map(toPendingFile);
        for (const file of nextFiles) {
          cancellationRef.current?.restoreFile(file.id);
        }
        return [...previous, ...nextFiles];
      });
    },
    [updatePendingFiles],
  );

  const removeFile = useCallback(
    (id: string): void => {
      cancelFile(id);
      updatePendingFiles((previous) =>
        previous.filter((file) => file.id !== id),
      );
    },
    [cancelFile, updatePendingFiles],
  );

  const clearFiles = useCallback((): void => {
    for (const file of pendingFilesRef.current) {
      cancelFile(file.id);
    }
    updatePendingFiles(() => []);
  }, [cancelFile, updatePendingFiles]);

  const resetDoneFiles = useCallback((): void => {
    updatePendingFiles((previous) =>
      previous.map((file) =>
        file.status === "done" ? { ...file, status: "pending" } : file,
      ),
    );
  }, [updatePendingFiles]);

  useEffect(
    () => () => {
      cancellationRef.current?.cancelFiles(
        pendingFilesRef.current.map((file) => file.id),
      );
    },
    [],
  );

  const uploadAll = useCallback(
    async (agentId: string): Promise<UploadedFile[]> => {
      const uploaded: UploadedFile[] = [];
      const currentFiles = pendingFilesRef.current.filter(shouldUpload);

      for (const pendingFile of currentFiles) {
        if (cancellationRef.current?.isCancelled(pendingFile.id)) {
          continue;
        }

        const operation: UploadOperation = {
          task: null,
          cancelled: false,
        };
        cancellationRef.current?.registerOperation(pendingFile.id, operation);
        updatePendingFiles((previous) =>
          previous.map((file) =>
            file.id === pendingFile.id
              ? updatePendingFileStatus(file, "uploading")
              : file,
          ),
        );

        try {
          operation.task = startBrowserFileUpload({
            agentId,
            file: pendingFile.file,
          });
          const uploadedFile = await operation.task.promise;

          if (operation.cancelled) {
            continue;
          }
          uploaded.push(uploadedFile);
          updatePendingFiles((previous) =>
            previous.map((file) =>
              file.id === pendingFile.id
                ? updatePendingFileStatus(file, "done")
                : file,
            ),
          );
        } catch (error) {
          if (operation.cancelled) {
            continue;
          }
          const failure = getUploadFailure(error);
          updatePendingFiles((previous) =>
            previous.map((file) =>
              file.id === pendingFile.id
                ? {
                    ...updatePendingFileStatus(file, "error"),
                    errorReason: failure.reason,
                    errorRetryable: failure.retryable,
                    ...(failure.detail ? { errorDetail: failure.detail } : {}),
                  }
                : file,
            ),
          );
          throw error;
        } finally {
          cancellationRef.current?.unregisterOperation(pendingFile.id);
        }
      }

      return uploaded;
    },
    [updatePendingFiles],
  );

  const isUploading = pendingFiles.some((file) => file.status === "uploading");

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
