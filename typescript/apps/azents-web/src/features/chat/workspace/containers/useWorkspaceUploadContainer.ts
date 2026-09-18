"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { startWorkspaceFileHash } from "../workspaceUploadHash";
import { pollWorkspaceUploadStatus } from "../workspaceUploadPolling";
import {
  startWorkspaceUploadPut,
  type WorkspaceUploadPutTask,
} from "../workspaceUploadTransport";
import { isTerminalWorkspaceUploadPhase } from "../workspaceUploadTypes";
import type {
  WorkspaceUploadContainerOutput,
  WorkspaceUploadRow,
  WorkspaceUploadUiPhase,
} from "../workspaceUploadTypes";
import type { WorkspaceUploadStatusResponse } from "@azents/public-client";

const STATUS_POLL_INTERVAL_MS = 750;

interface UseWorkspaceUploadContainerInput {
  agentId: string;
  sessionId: string;
  destinationDirectory: string;
  onDestinationChanged: (destinationDirectory: string) => Promise<void> | void;
}

interface HashTask {
  promise: Promise<string>;
  cancel: () => void;
}

interface UploadOperation {
  agentId: string;
  sessionId: string;
  row: WorkspaceUploadRow;
  file: File;
  destinationDirectory: string;
  uploadId: string | null;
  revision: number | null;
  currentDeliveryNumber: number | null;
  hashTask: HashTask | null;
  putTask: WorkspaceUploadPutTask | null;
  pollTimer: number | null;
  pollWaitResolver: (() => void) | null;
  cancelRequested: boolean;
  cancelPromise: Promise<void> | null;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim() !== "") {
    return error.message;
  }
  return "Workspace upload failed.";
}

function joinDestinationPath(directory: string, filename: string): string {
  return `${directory.replace(/\/+$/, "")}/${filename}`;
}

function createRowId(): string {
  return globalThis.crypto.randomUUID();
}

function clearStatusWait(operation: UploadOperation): void {
  if (operation.pollTimer !== null) {
    window.clearTimeout(operation.pollTimer);
    operation.pollTimer = null;
  }
  const resolve = operation.pollWaitResolver;
  operation.pollWaitResolver = null;
  resolve?.();
}

function isCancelRequested(operation: UploadOperation): boolean {
  return operation.cancelRequested;
}

function mapServerPhase(
  phase: WorkspaceUploadStatusResponse["phase"],
): WorkspaceUploadUiPhase {
  switch (phase) {
    case "queued":
      return "moving_to_runtime";
    case "uploading":
      return "uploading";
    case "moving_to_runtime":
      return "moving_to_runtime";
    case "conflicted":
      return "conflicted";
    case "retryable_failure":
    case "failed":
    case "expired":
      return "failed";
    case "succeeded":
      return "succeeded";
    case "cancelled":
      return "cancelled";
  }
}

function progressForStatus(status: WorkspaceUploadStatusResponse): number {
  if (status.phase === "succeeded") {
    return 100;
  }
  if (status.expected_size === 0 && status.phase === "moving_to_runtime") {
    return 100;
  }
  if (status.expected_size <= 0) {
    return 0;
  }
  return Math.min(
    100,
    Math.round((status.received_size / status.expected_size) * 100),
  );
}

export function useWorkspaceUploadContainer({
  agentId,
  sessionId,
  destinationDirectory,
  onDestinationChanged,
}: UseWorkspaceUploadContainerInput): WorkspaceUploadContainerOutput {
  const [rows, setRows] = useState<WorkspaceUploadRow[]>([]);
  const rowsRef = useRef<WorkspaceUploadRow[]>([]);
  const operationsRef = useRef(new Map<string, UploadOperation>());
  const mountedRef = useRef(true);
  const settleCancellationRef = useRef<
    ((operation: UploadOperation) => Promise<void>) | null
  >(null);
  const utils = trpc.useUtils();
  const createMutation = trpc.chat.createAgentWorkspaceUpload.useMutation();
  const finalizeMutation = trpc.chat.finalizeAgentWorkspaceUpload.useMutation();
  const cancelMutation = trpc.chat.cancelAgentWorkspaceUpload.useMutation();
  const retryMutation = trpc.chat.retryAgentWorkspaceUpload.useMutation();

  const updateRow = useCallback(
    (
      id: string,
      update: (row: WorkspaceUploadRow) => WorkspaceUploadRow,
    ): void => {
      if (!mountedRef.current) {
        return;
      }
      setRows((previous) => {
        const next = previous.map((row) => (row.id === id ? update(row) : row));
        rowsRef.current = next;
        return next;
      });
    },
    [],
  );

  const updateRowFromStatus = useCallback(
    (
      operation: UploadOperation,
      status: WorkspaceUploadStatusResponse,
    ): void => {
      operation.uploadId = status.identity.upload_id;
      operation.revision = status.revision;
      operation.currentDeliveryNumber = status.current_delivery_number ?? null;
      const conflictPrecondition =
        status.destination_evidence?.conflict_precondition ?? null;
      updateRow(operation.row.id, (row) => ({
        ...row,
        phase: mapServerPhase(status.phase),
        progress: Math.max(row.progress, progressForStatus(status)),
        transferredBytes: Math.max(row.transferredBytes, status.received_size),
        uploadId: status.identity.upload_id,
        revision: status.revision,
        currentDeliveryNumber: status.current_delivery_number ?? null,
        failure: status.failure ?? null,
        errorMessage: null,
        retryAvailable: status.retry_available,
        serverRetryAvailable: status.retry_available,
        overwriteAvailable:
          status.overwrite_available && conflictPrecondition !== null,
        conflictPrecondition,
      }));
    },
    [updateRow],
  );

  const invalidateDestination = useCallback(
    async (directory: string): Promise<void> => {
      await Promise.all([
        utils.chat.getAgentWorkspace.invalidate({ agentId }),
        utils.chat.readAgentWorkspacePath.invalidate({
          agentId,
          sessionId,
          path: directory,
        }),
      ]);
      await onDestinationChanged(directory);
    },
    [
      agentId,
      onDestinationChanged,
      sessionId,
      utils.chat.getAgentWorkspace,
      utils.chat.readAgentWorkspacePath,
    ],
  );

  const waitForStatusPoll = useCallback(
    (operation: UploadOperation): Promise<void> =>
      new Promise<void>((resolve) => {
        operation.pollWaitResolver = resolve;
        operation.pollTimer = window.setTimeout(() => {
          operation.pollTimer = null;
          operation.pollWaitResolver = null;
          resolve();
        }, STATUS_POLL_INTERVAL_MS);
      }),
    [],
  );

  const pollCancellationStatus = useCallback(
    async (operation: UploadOperation): Promise<void> => {
      if (operation.uploadId === null) {
        return;
      }
      try {
        await pollWorkspaceUploadStatus({
          fetchStatus: (input, options) =>
            utils.chat.getAgentWorkspaceUpload.fetch(input, options),
          input: {
            agentId: operation.agentId,
            uploadId: operation.uploadId,
          },
          isTerminal: (status) => isTerminalWorkspaceUploadPhase(status.phase),
          onStatus: async (status) => {
            updateRowFromStatus(operation, status);
            if (status.phase === "succeeded") {
              await invalidateDestination(operation.destinationDirectory);
            }
          },
          wait: () => waitForStatusPoll(operation),
        });
      } catch (error: unknown) {
        updateRow(operation.row.id, (row) => ({
          ...row,
          phase: "failed",
          failure: "cancelled",
          errorMessage: getErrorMessage(error),
          retryAvailable: true,
          serverRetryAvailable: false,
          overwriteAvailable: false,
          conflictPrecondition: null,
        }));
      }
    },
    [
      invalidateDestination,
      updateRow,
      updateRowFromStatus,
      utils.chat.getAgentWorkspaceUpload,
      waitForStatusPoll,
    ],
  );

  const settleCancellation = useCallback(
    async (operation: UploadOperation): Promise<void> => {
      clearStatusWait(operation);
      if (operation.cancelPromise) {
        await operation.cancelPromise;
        return;
      }
      if (operation.uploadId === null || operation.revision === null) {
        updateRow(operation.row.id, (row) => ({
          ...row,
          phase: "cancelled",
          errorMessage: null,
          retryAvailable: false,
          serverRetryAvailable: false,
          overwriteAvailable: false,
          conflictPrecondition: null,
        }));
        return;
      }
      operation.cancelPromise = cancelMutation
        .mutateAsync({
          agentId: operation.agentId,
          uploadId: operation.uploadId,
          expectedRevision: operation.revision,
          currentDeliveryNumber: operation.currentDeliveryNumber,
        })
        .then(async (status) => {
          updateRowFromStatus(operation, status);
          if (!isTerminalWorkspaceUploadPhase(status.phase)) {
            await pollCancellationStatus(operation);
          } else if (status.phase === "succeeded") {
            await invalidateDestination(operation.destinationDirectory);
          }
        })
        .catch((error: unknown) => {
          updateRow(operation.row.id, (row) => ({
            ...row,
            phase: "failed",
            failure: "cancelled",
            errorMessage: getErrorMessage(error),
            retryAvailable: true,
            serverRetryAvailable: false,
            overwriteAvailable: false,
            conflictPrecondition: null,
          }));
        });
      await operation.cancelPromise;
    },
    [
      cancelMutation,
      invalidateDestination,
      pollCancellationStatus,
      updateRow,
      updateRowFromStatus,
    ],
  );

  const waitForStatus = useCallback(
    async (operation: UploadOperation): Promise<void> => {
      if (operation.uploadId === null) {
        return;
      }
      for (;;) {
        if (isCancelRequested(operation)) {
          await settleCancellation(operation);
          return;
        }

        let status: WorkspaceUploadStatusResponse;
        try {
          status = await utils.chat.getAgentWorkspaceUpload.fetch(
            {
              agentId: operation.agentId,
              uploadId: operation.uploadId,
            },
            { staleTime: 0 },
          );
        } catch (error: unknown) {
          if (isCancelRequested(operation)) {
            await settleCancellation(operation);
            return;
          }
          updateRow(operation.row.id, (row) => ({
            ...row,
            phase: "failed",
            failure: "transfer",
            errorMessage: getErrorMessage(error),
            retryAvailable: true,
            serverRetryAvailable: operation.currentDeliveryNumber !== null,
            overwriteAvailable: false,
            conflictPrecondition: null,
          }));
          return;
        }

        updateRowFromStatus(operation, status);
        if (isTerminalWorkspaceUploadPhase(status.phase)) {
          if (status.phase === "succeeded") {
            await invalidateDestination(operation.destinationDirectory);
          }
          return;
        }
        await waitForStatusPoll(operation);
      }
    },
    [
      invalidateDestination,
      settleCancellation,
      updateRow,
      updateRowFromStatus,
      utils.chat.getAgentWorkspaceUpload,
      waitForStatusPoll,
    ],
  );

  const runUpload = useCallback(
    async (operation: UploadOperation): Promise<void> => {
      try {
        operation.hashTask = startWorkspaceFileHash(
          operation.file,
          (loadedBytes, totalBytes) => {
            updateRow(operation.row.id, (row) => ({
              ...row,
              phase: "hashing",
              progress:
                totalBytes > 0
                  ? Math.round((loadedBytes / totalBytes) * 20)
                  : 0,
              transferredBytes: loadedBytes,
            }));
          },
        );
        const sha256 = await operation.hashTask.promise;
        operation.hashTask = null;
        if (isCancelRequested(operation)) {
          await settleCancellation(operation);
          return;
        }

        const created = await createMutation.mutateAsync({
          agentId: operation.agentId,
          destinationDirectory: operation.destinationDirectory,
          filename: operation.file.name,
          expectedSize: operation.file.size,
          expectedSha256: sha256,
          mediaType: operation.file.type || null,
          sessionId: operation.sessionId,
        });
        updateRowFromStatus(operation, created.status);
        operation.uploadId = created.status.identity.upload_id;
        operation.revision = created.status.revision;
        if (isCancelRequested(operation)) {
          await settleCancellation(operation);
          return;
        }

        updateRow(operation.row.id, (row) => ({
          ...row,
          phase: "uploading",
          progress: Math.max(row.progress, 20),
          errorMessage: null,
        }));
        operation.putTask = startWorkspaceUploadPut({
          url: created.ticket.url,
          method: created.ticket.method,
          headers: created.ticket.headers,
          file: operation.file,
          onProgress: (loadedBytes, totalBytes) => {
            updateRow(operation.row.id, (row) => ({
              ...row,
              phase: "uploading",
              progress:
                20 +
                (totalBytes > 0
                  ? Math.round((loadedBytes / totalBytes) * 55)
                  : 0),
              transferredBytes: loadedBytes,
            }));
          },
        });
        await operation.putTask.promise;
        operation.putTask = null;
        if (isCancelRequested(operation)) {
          await settleCancellation(operation);
          return;
        }

        updateRow(operation.row.id, (row) => ({
          ...row,
          phase: "moving_to_runtime",
          progress: Math.max(row.progress, 75),
        }));
        const finalized = await finalizeMutation.mutateAsync({
          agentId: operation.agentId,
          uploadId: operation.uploadId,
          expectedRevision: operation.revision,
        });
        updateRowFromStatus(operation, finalized);
        await waitForStatus(operation);
      } catch (error: unknown) {
        if (isCancelRequested(operation)) {
          await settleCancellation(operation);
          return;
        }

        if (operation.uploadId !== null && operation.revision !== null) {
          void cancelMutation
            .mutateAsync({
              agentId: operation.agentId,
              uploadId: operation.uploadId,
              expectedRevision: operation.revision,
              currentDeliveryNumber: operation.currentDeliveryNumber,
            })
            .catch(() => {});
        }
        updateRow(operation.row.id, (row) => ({
          ...row,
          phase: "failed",
          failure: "transfer",
          errorMessage: getErrorMessage(error),
          retryAvailable: true,
          serverRetryAvailable: false,
          overwriteAvailable: false,
          conflictPrecondition: null,
        }));
      } finally {
        operation.hashTask = null;
        operation.putTask = null;
      }
    },
    [
      cancelMutation,
      createMutation,
      finalizeMutation,
      settleCancellation,
      updateRow,
      updateRowFromStatus,
      waitForStatus,
    ],
  );

  const uploadFiles = useCallback(
    (files: FileList | File[]): void => {
      const selectedFiles = Array.from(files);
      if (selectedFiles.length === 0) {
        return;
      }
      const newRows = selectedFiles.map<WorkspaceUploadRow>((file) => ({
        id: createRowId(),
        filename: file.name,
        destinationPath: joinDestinationPath(destinationDirectory, file.name),
        expectedSize: file.size,
        phase: "queued",
        progress: 0,
        transferredBytes: 0,
        uploadId: null,
        revision: null,
        currentDeliveryNumber: null,
        failure: null,
        errorMessage: null,
        retryAvailable: false,
        serverRetryAvailable: false,
        overwriteAvailable: false,
        conflictPrecondition: null,
      }));
      setRows((previous) => {
        const next = [...previous, ...newRows];
        rowsRef.current = next;
        return next;
      });
      newRows.forEach((row, index) => {
        const file = selectedFiles[index];
        if (!file) {
          return;
        }
        const operation: UploadOperation = {
          agentId,
          sessionId,
          row,
          file,
          destinationDirectory,
          uploadId: null,
          revision: null,
          currentDeliveryNumber: null,
          hashTask: null,
          putTask: null,
          pollTimer: null,
          pollWaitResolver: null,
          cancelRequested: false,
          cancelPromise: null,
        };
        operationsRef.current.set(row.id, operation);
        void runUpload(operation);
      });
    },
    [agentId, destinationDirectory, runUpload, sessionId],
  );

  const cancelUpload = useCallback(
    (id: string): void => {
      const operation = operationsRef.current.get(id);
      if (!operation) {
        return;
      }
      operation.cancelRequested = true;
      operation.hashTask?.cancel();
      operation.putTask?.abort();
      clearStatusWait(operation);
      void settleCancellation(operation);
    },
    [settleCancellation],
  );

  const retryUpload = useCallback(
    (id: string, overwrite: boolean): void => {
      const operation = operationsRef.current.get(id);
      const row = rowsRef.current.find((value) => value.id === id);
      if (!operation || !row || !row.retryAvailable) {
        return;
      }
      if (
        row.serverRetryAvailable &&
        operation.uploadId !== null &&
        operation.revision !== null &&
        operation.currentDeliveryNumber !== null
      ) {
        if (overwrite && row.conflictPrecondition === null) {
          return;
        }
        const conflictPrecondition = overwrite
          ? row.conflictPrecondition
          : null;
        updateRow(id, (current) => ({
          ...current,
          phase: "moving_to_runtime",
          progress: Math.max(current.progress, 75),
          errorMessage: null,
          failure: null,
          retryAvailable: false,
          serverRetryAvailable: false,
          overwriteAvailable: false,
          conflictPrecondition: null,
        }));
        void retryMutation
          .mutateAsync({
            agentId,
            uploadId: operation.uploadId,
            expectedRevision: operation.revision,
            currentDeliveryNumber: operation.currentDeliveryNumber,
            overwrite,
            conflictPrecondition,
          })
          .then((status) => {
            updateRowFromStatus(operation, status);
            return waitForStatus(operation);
          })
          .catch((error: unknown) => {
            updateRow(id, (current) => ({
              ...current,
              phase: "failed",
              failure: "transfer",
              errorMessage: getErrorMessage(error),
              retryAvailable: true,
              serverRetryAvailable: true,
              overwriteAvailable: overwrite,
              conflictPrecondition,
            }));
          });
        return;
      }

      operation.uploadId = null;
      operation.revision = null;
      operation.currentDeliveryNumber = null;
      operation.cancelRequested = false;
      operation.cancelPromise = null;
      updateRow(id, (current) => ({
        ...current,
        phase: "queued",
        progress: 0,
        transferredBytes: 0,
        uploadId: null,
        revision: null,
        currentDeliveryNumber: null,
        failure: null,
        errorMessage: null,
        retryAvailable: false,
        serverRetryAvailable: false,
        overwriteAvailable: false,
        conflictPrecondition: null,
      }));
      void runUpload(operation);
    },
    [
      agentId,
      retryMutation,
      runUpload,
      updateRow,
      updateRowFromStatus,
      waitForStatus,
    ],
  );

  settleCancellationRef.current = settleCancellation;
  useEffect(() => {
    mountedRef.current = true;
    rowsRef.current = [];
    setRows([]);
    const operations = operationsRef.current;
    return () => {
      mountedRef.current = false;
      for (const operation of operations.values()) {
        operation.cancelRequested = true;
        operation.hashTask?.cancel();
        operation.putTask?.abort();
        clearStatusWait(operation);
        void settleCancellationRef.current?.(operation);
      }
      operations.clear();
    };
  }, [agentId, sessionId]);

  const dismissUpload = useCallback((id: string): void => {
    const row = rowsRef.current.find((value) => value.id === id);
    if (
      row &&
      (row.phase === "hashing" ||
        row.phase === "uploading" ||
        row.phase === "moving_to_runtime")
    ) {
      return;
    }
    operationsRef.current.delete(id);
    setRows((previous) => {
      const next = previous.filter((value) => value.id !== id);
      rowsRef.current = next;
      return next;
    });
  }, []);

  return {
    rows,
    hasActiveUploads: rows.some(
      (row) =>
        row.phase === "hashing" ||
        row.phase === "uploading" ||
        row.phase === "moving_to_runtime",
    ),
    uploadFiles,
    cancelUpload,
    retryUpload,
    dismissUpload,
  };
}
