export interface FileUploadCancellationCoordinator<Operation> {
  cancelFile: (fileId: string) => void;
  cancelFiles: (fileIds: readonly string[]) => void;
  isCancelled: (fileId: string) => boolean;
  registerOperation: (fileId: string, operation: Operation) => void;
  restoreFile: (fileId: string) => void;
  unregisterOperation: (fileId: string) => void;
}

export function createFileUploadCancellationCoordinator<Operation>(
  cancelOperation: (operation: Operation) => void,
): FileUploadCancellationCoordinator<Operation> {
  const cancelledFileIds = new Set<string>();
  const operations = new Map<string, Operation>();

  function cancelFile(fileId: string): void {
    cancelledFileIds.add(fileId);
    const operation = operations.get(fileId);
    if (operation) {
      cancelOperation(operation);
    }
  }

  return {
    cancelFile,
    cancelFiles: (fileIds: readonly string[]): void => {
      for (const fileId of fileIds) {
        cancelledFileIds.add(fileId);
      }
      for (const fileId of fileIds) {
        const operation = operations.get(fileId);
        if (operation) {
          cancelOperation(operation);
        }
      }
    },
    isCancelled: (fileId: string): boolean => cancelledFileIds.has(fileId),
    registerOperation: (fileId: string, operation: Operation): void => {
      operations.set(fileId, operation);
    },
    restoreFile: (fileId: string): void => {
      cancelledFileIds.delete(fileId);
    },
    unregisterOperation: (fileId: string): void => {
      operations.delete(fileId);
    },
  };
}
