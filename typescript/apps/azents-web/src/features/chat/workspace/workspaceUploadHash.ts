interface HashWorkerProgress {
  type: "progress";
  loadedBytes: number;
  totalBytes: number;
}

interface HashWorkerDone {
  type: "done";
  sha256: string;
}

type HashWorkerResponse = HashWorkerProgress | HashWorkerDone;

export interface WorkspaceFileHashTask {
  promise: Promise<string>;
  cancel: () => void;
}

/**
 * Start hashing one File in a dedicated worker.
 *
 * The worker reads bounded `File.slice()` chunks and reports progress. Keeping
 * the worker lifecycle explicit lets a cancelled upload release the worker
 * immediately instead of waiting for a large local file to finish hashing.
 */
export function startWorkspaceFileHash(
  file: File,
  onProgress: (loadedBytes: number, totalBytes: number) => void,
): WorkspaceFileHashTask {
  const worker = new Worker(
    new URL("./workspaceUploadHash.worker.ts", import.meta.url),
    { type: "module" },
  );
  let settled = false;
  let rejectPromise: ((reason?: unknown) => void) | null = null;

  const promise = new Promise<string>((resolve, reject) => {
    rejectPromise = reject;
    worker.onmessage = (event: MessageEvent<HashWorkerResponse>): void => {
      if (event.data.type === "progress") {
        onProgress(event.data.loadedBytes, event.data.totalBytes);
        return;
      }
      settled = true;
      worker.terminate();
      resolve(event.data.sha256);
    };
    worker.onerror = (): void => {
      settled = true;
      worker.terminate();
      reject(new Error("Could not prepare the file checksum."));
    };
    worker.postMessage({ file });
  });

  return {
    promise,
    cancel: (): void => {
      if (settled) {
        return;
      }
      settled = true;
      worker.terminate();
      rejectPromise?.(new Error("File checksum preparation was cancelled."));
    },
  };
}
