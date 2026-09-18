export interface WorkspaceUploadPutTask {
  promise: Promise<void>;
  abort: () => void;
}

export interface WorkspaceUploadPutInput {
  url: string;
  method: "PUT";
  headers: Record<string, string>;
  file: File;
  onProgress: (loadedBytes: number, totalBytes: number) => void;
}

/**
 * Upload directly to the presigned object-storage URL with browser progress.
 *
 * XMLHttpRequest is used because fetch does not expose upload progress in the
 * browsers supported by the Web application.
 */
export function startWorkspaceUploadPut(
  input: WorkspaceUploadPutInput,
): WorkspaceUploadPutTask {
  const request = new XMLHttpRequest();
  let rejectPromise: ((reason?: unknown) => void) | null = null;

  const promise = new Promise<void>((resolve, reject) => {
    rejectPromise = reject;
    request.open(input.method, input.url);
    Object.entries(input.headers).forEach(([name, value]) => {
      request.setRequestHeader(name, value);
    });
    request.upload.onprogress = (event): void => {
      if (event.lengthComputable) {
        input.onProgress(event.loaded, event.total);
      } else {
        input.onProgress(event.loaded, input.file.size);
      }
    };
    request.onload = (): void => {
      if (request.status >= 200 && request.status < 300) {
        input.onProgress(input.file.size, input.file.size);
        resolve();
        return;
      }
      reject(new Error(`Direct upload failed (${request.status}).`));
    };
    request.onerror = (): void => {
      reject(
        new Error(
          "Direct upload failed because the storage request was unavailable.",
        ),
      );
    };
    request.onabort = (): void => {
      reject(new Error("Direct upload was cancelled."));
    };
    request.send(input.file);
  });

  return {
    promise,
    abort: (): void => {
      if (request.readyState !== XMLHttpRequest.DONE) {
        request.abort();
      } else {
        rejectPromise?.(new Error("Direct upload was cancelled."));
      }
    },
  };
}
