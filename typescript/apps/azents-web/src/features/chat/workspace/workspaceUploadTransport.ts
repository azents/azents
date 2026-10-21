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

export interface WorkspaceUploadRequest {
  readonly done: boolean;
  readonly status: number;
  open: (method: "PUT", url: string) => void;
  setRequestHeader: (name: string, value: string) => void;
  send: (file: File) => void;
  abort: () => void;
  setProgressHandler: (
    callback: (
      loaded: number,
      total: number,
      lengthComputable: boolean,
    ) => void,
  ) => void;
  setLoadHandler: (callback: () => void) => void;
  setErrorHandler: (callback: () => void) => void;
  setAbortHandler: (callback: () => void) => void;
}

function createBrowserUploadRequest(): WorkspaceUploadRequest {
  const request = new XMLHttpRequest();
  return {
    get done() {
      return request.readyState === XMLHttpRequest.DONE;
    },
    get status() {
      return request.status;
    },
    open: (method, url) => request.open(method, url),
    setRequestHeader: (name, value) => request.setRequestHeader(name, value),
    send: (file) => request.send(file),
    abort: () => request.abort(),
    setProgressHandler: (callback) => {
      request.upload.onprogress = (event) =>
        callback(event.loaded, event.total, event.lengthComputable);
    },
    setLoadHandler: (callback) => {
      request.onload = callback;
    },
    setErrorHandler: (callback) => {
      request.onerror = callback;
    },
    setAbortHandler: (callback) => {
      request.onabort = callback;
    },
  };
}

/**
 * Upload directly to the presigned object-storage URL with browser progress.
 *
 * XMLHttpRequest is used because fetch does not expose upload progress in the
 * browsers supported by the Web application.
 */
export function startWorkspaceUploadPut(
  input: WorkspaceUploadPutInput,
  createRequest: () => WorkspaceUploadRequest = createBrowserUploadRequest,
): WorkspaceUploadPutTask {
  const request = createRequest();
  let rejectPromise: ((reason?: unknown) => void) | null = null;

  const promise = new Promise<void>((resolve, reject) => {
    rejectPromise = reject;
    request.open(input.method, input.url);
    Object.entries(input.headers).forEach(([name, value]) => {
      request.setRequestHeader(name, value);
    });
    request.setProgressHandler((loaded, total, lengthComputable): void => {
      if (lengthComputable) {
        input.onProgress(loaded, total);
      } else {
        input.onProgress(loaded, input.file.size);
      }
    });
    request.setLoadHandler((): void => {
      if (request.status >= 200 && request.status < 300) {
        input.onProgress(input.file.size, input.file.size);
        resolve();
        return;
      }
      reject(new Error(`Direct upload failed (${request.status}).`));
    });
    request.setErrorHandler((): void => {
      reject(
        new Error(
          "Direct upload failed because the storage request was unavailable.",
        ),
      );
    });
    request.setAbortHandler((): void => {
      reject(new Error("Direct upload was cancelled."));
    });
    request.send(input.file);
  });

  return {
    promise,
    abort: (): void => {
      if (!request.done) {
        request.abort();
      } else {
        rejectPromise?.(new Error("Direct upload was cancelled."));
      }
    },
  };
}
