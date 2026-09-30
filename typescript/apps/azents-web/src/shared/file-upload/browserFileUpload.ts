import { type FileHashTask, startFileHash } from "./fileHash.ts";

export const MAX_FILE_UPLOAD_BYTES = 128 * 1024 * 1024;

export interface UploadedBrowserFile {
  attachmentId: string;
  uri: string;
  name: string;
  mediaType: string;
  size: number;
}

export interface BrowserFileUploadInput {
  agentId: string;
  file: File;
  onHashProgress?: (loadedBytes: number, totalBytes: number) => void;
}

export interface BrowserFileUploadTask {
  promise: Promise<UploadedBrowserFile>;
  cancel: () => void;
}

export interface BrowserFileUploadDependencies {
  fetch: typeof globalThis.fetch;
  startFileHash: (
    file: File,
    onProgress: (loadedBytes: number, totalBytes: number) => void,
  ) => FileHashTask;
}

interface UploadPreparation {
  upload_id: string;
  put_url: string;
  put_headers: Record<string, string>;
  expires_at: string;
}

interface UploadResponse {
  attachment_id: string;
  uri: string;
  media_type: string;
  size: number;
  name?: string;
}

const DEFAULT_DEPENDENCIES: BrowserFileUploadDependencies = {
  fetch: (input, init): Promise<Response> => globalThis.fetch(input, init),
  startFileHash,
};

export class BrowserFileUploadHttpError extends Error {
  public readonly status: number;

  public readonly body: unknown;

  public constructor(status: number, body: unknown) {
    super(`File upload request failed (${status}).`);
    this.name = "BrowserFileUploadHttpError";
    this.status = status;
    this.body = body;
  }
}

export class BrowserFileUploadInvalidResponseError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = "BrowserFileUploadInvalidResponseError";
  }
}

export function isFileUploadSizeAllowed(size: number): boolean {
  return (
    Number.isSafeInteger(size) && size >= 0 && size <= MAX_FILE_UPLOAD_BYTES
  );
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every((entry) => typeof entry === "string")
  );
}

function isUploadPreparation(value: unknown): value is UploadPreparation {
  return (
    typeof value === "object" &&
    value !== null &&
    "upload_id" in value &&
    typeof value.upload_id === "string" &&
    "put_url" in value &&
    typeof value.put_url === "string" &&
    "put_headers" in value &&
    isStringRecord(value.put_headers) &&
    "expires_at" in value &&
    typeof value.expires_at === "string"
  );
}

function isUploadResponse(value: unknown): value is UploadResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "attachment_id" in value &&
    typeof value.attachment_id === "string" &&
    "uri" in value &&
    typeof value.uri === "string" &&
    "media_type" in value &&
    typeof value.media_type === "string" &&
    "size" in value &&
    typeof value.size === "number" &&
    (!("name" in value) || typeof value.name === "string")
  );
}

async function readErrorBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function readPreparation(response: Response): Promise<UploadPreparation> {
  const data: unknown = await response.json();
  if (!isUploadPreparation(data)) {
    throw new BrowserFileUploadInvalidResponseError(
      "Invalid upload preparation response.",
    );
  }
  return data;
}

async function readFinalizedFile(
  response: Response,
  file: File,
): Promise<UploadedBrowserFile> {
  const data: unknown = await response.json();
  if (!isUploadResponse(data)) {
    throw new BrowserFileUploadInvalidResponseError("Invalid upload response.");
  }
  return {
    attachmentId: data.attachment_id,
    uri: data.uri,
    name: data.name || file.name,
    mediaType: data.media_type,
    size: data.size,
  };
}

async function requireSuccess(response: Response): Promise<void> {
  if (!response.ok) {
    throw new BrowserFileUploadHttpError(
      response.status,
      await readErrorBody(response),
    );
  }
}

export function startBrowserFileUpload(
  input: BrowserFileUploadInput,
  dependencies: BrowserFileUploadDependencies = DEFAULT_DEPENDENCIES,
): BrowserFileUploadTask {
  const abortController = new AbortController();
  const hashTask = dependencies.startFileHash(
    input.file,
    input.onHashProgress ?? (() => {}),
  );

  const promise = (async (): Promise<UploadedBrowserFile> => {
    const sha256 = await hashTask.promise;
    const prepareResponse = await dependencies.fetch("/api/chat/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agentId: input.agentId,
        filename: input.file.name,
        media_type: input.file.type || "application/octet-stream",
        size: input.file.size,
        sha256,
      }),
      signal: abortController.signal,
    });
    await requireSuccess(prepareResponse);
    const preparation = await readPreparation(prepareResponse);

    const putResponse = await dependencies.fetch(preparation.put_url, {
      method: "PUT",
      headers: preparation.put_headers,
      body: input.file,
      signal: abortController.signal,
    });
    await requireSuccess(putResponse);

    const finalizeResponse = await dependencies.fetch(
      `/api/chat/upload/${encodeURIComponent(preparation.upload_id)}/finalize`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agentId: input.agentId }),
        signal: abortController.signal,
      },
    );
    await requireSuccess(finalizeResponse);
    return readFinalizedFile(finalizeResponse, input.file);
  })();

  return {
    promise,
    cancel: (): void => {
      hashTask.cancel();
      abortController.abort();
    },
  };
}
