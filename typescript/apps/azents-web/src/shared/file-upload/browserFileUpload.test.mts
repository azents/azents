import assert from "node:assert/strict";
import test from "node:test";
import {
  type BrowserFileUploadDependencies,
  BrowserFileUploadHttpError,
  isFileUploadSizeAllowed,
  MAX_FILE_UPLOAD_BYTES,
  startBrowserFileUpload,
} from "./browserFileUpload.ts";
import type { FileHashTask } from "./fileHash.ts";

interface FetchCall {
  input: RequestInfo | URL;
  init?: RequestInit;
}

function file(): File {
  return new File(["file-body"], "report.txt", { type: "text/plain" });
}

function resolvedHashTask(sha256 = "a".repeat(64)): FileHashTask {
  return {
    promise: Promise.resolve(sha256),
    cancel: (): void => {},
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function dependencies(
  responses: Response[],
  hashTask: FileHashTask = resolvedHashTask(),
): { dependencies: BrowserFileUploadDependencies; calls: FetchCall[] } {
  const calls: FetchCall[] = [];
  return {
    dependencies: {
      fetch: (
        input: RequestInfo | URL,
        init?: RequestInit,
      ): Promise<Response> => {
        calls.push({ input, init });
        const response = responses.shift();
        assert.ok(response, "Unexpected upload request");
        return Promise.resolve(response);
      },
      startFileHash: (): FileHashTask => hashTask,
    },
    calls,
  };
}

function requestBody(call: FetchCall): Record<string, unknown> {
  const body = call.init?.body;
  if (typeof body !== "string") {
    throw new Error("Expected a JSON request body.");
  }
  const parsed: unknown = JSON.parse(body);
  if (!isRecord(parsed)) {
    throw new Error("Expected a JSON object request body.");
  }
  return parsed;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function callAt(calls: FetchCall[], index: number): FetchCall {
  const call = calls[index];
  if (!call) {
    throw new Error(`Expected fetch call ${index}.`);
  }
  return call;
}

void test("allows a 128 MiB file and rejects one byte beyond the limit", () => {
  assert.equal(isFileUploadSizeAllowed(MAX_FILE_UPLOAD_BYTES), true);
  assert.equal(isFileUploadSizeAllowed(MAX_FILE_UPLOAD_BYTES + 1), false);
});

void test("hashes, prepares metadata, directly PUTs signed headers, then finalizes", async () => {
  const selectedFile = file();
  const { dependencies: uploadDependencies, calls } = dependencies([
    jsonResponse({
      upload_id: "upload-1",
      put_url: "https://storage.example/opaque-signed-url",
      put_headers: {
        "Content-Type": "text/plain",
        "x-amz-meta-checksum": "a".repeat(64),
      },
      expires_at: "2026-09-29T12:00:00Z",
    }),
    new Response(null, { status: 204 }),
    jsonResponse({
      attachment_id: "attachment-1",
      uri: "exchange://attachment-1",
      media_type: "text/plain",
      size: selectedFile.size,
    }),
  ]);

  const task = startBrowserFileUpload(
    { agentId: "agent-1", file: selectedFile },
    uploadDependencies,
  );
  const uploaded = await task.promise;

  assert.deepEqual(uploaded, {
    attachmentId: "attachment-1",
    uri: "exchange://attachment-1",
    name: "report.txt",
    mediaType: "text/plain",
    size: selectedFile.size,
  });
  assert.equal(calls.length, 3);
  const prepareCall = callAt(calls, 0);
  const putCall = callAt(calls, 1);
  const finalizeCall = callAt(calls, 2);
  assert.equal(prepareCall.input, "/api/chat/upload");
  assert.deepEqual(requestBody(prepareCall), {
    agentId: "agent-1",
    filename: "report.txt",
    media_type: "text/plain",
    size: selectedFile.size,
    sha256: "a".repeat(64),
  });
  assert.equal(putCall.input, "https://storage.example/opaque-signed-url");
  assert.equal(putCall.init?.method, "PUT");
  assert.deepEqual(putCall.init.headers, {
    "Content-Type": "text/plain",
    "x-amz-meta-checksum": "a".repeat(64),
  });
  assert.equal(putCall.init.body, selectedFile);
  assert.equal(finalizeCall.input, "/api/chat/upload/upload-1/finalize");
  assert.deepEqual(requestBody(finalizeCall), { agentId: "agent-1" });
});

void test("does not finalize when the direct PUT fails", async () => {
  const { dependencies: uploadDependencies, calls } = dependencies([
    jsonResponse({
      upload_id: "upload-1",
      put_url: "https://storage.example/opaque-signed-url",
      put_headers: {},
      expires_at: "2026-09-29T12:00:00Z",
    }),
    jsonResponse({ detail: "Signature rejected" }, 403),
  ]);

  const task = startBrowserFileUpload(
    { agentId: "agent-1", file: file() },
    uploadDependencies,
  );

  await assert.rejects(task.promise, (error: unknown): boolean => {
    assert.ok(error instanceof BrowserFileUploadHttpError);
    assert.equal(error.status, 403);
    return true;
  });
  assert.equal(calls.length, 2);
});

void test("does not publish a file when finalize fails", async () => {
  const { dependencies: uploadDependencies, calls } = dependencies([
    jsonResponse({
      upload_id: "upload-1",
      put_url: "https://storage.example/opaque-signed-url",
      put_headers: {},
      expires_at: "2026-09-29T12:00:00Z",
    }),
    new Response(null, { status: 204 }),
    jsonResponse({ detail: "Upload expired" }, 410),
  ]);

  const task = startBrowserFileUpload(
    { agentId: "agent-1", file: file() },
    uploadDependencies,
  );

  await assert.rejects(task.promise, (error: unknown): boolean => {
    assert.ok(error instanceof BrowserFileUploadHttpError);
    assert.equal(error.status, 410);
    return true;
  });
  assert.equal(calls.length, 3);
});

void test("cancels a queued hash before it can prepare metadata", async () => {
  let rejectHash: ((reason?: unknown) => void) | null = null;
  let hashCancelled = false;
  const deferredHashTask: FileHashTask = {
    promise: new Promise<string>((_resolve, reject) => {
      rejectHash = reject;
    }),
    cancel: (): void => {
      hashCancelled = true;
      rejectHash?.(new Error("File checksum preparation was cancelled."));
    },
  };
  const { dependencies: uploadDependencies, calls } = dependencies(
    [],
    deferredHashTask,
  );

  const task = startBrowserFileUpload(
    { agentId: "agent-1", file: file() },
    uploadDependencies,
  );
  task.cancel();

  await assert.rejects(task.promise, /checksum preparation was cancelled/);
  assert.equal(hashCancelled, true);
  assert.equal(calls.length, 0);
});

void test("cancels an in-flight metadata request through its AbortSignal", async () => {
  let abortObserved = false;
  const uploadDependencies: BrowserFileUploadDependencies = {
    fetch: async (
      _input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            abortObserved = true;
            reject(
              new DOMException("The operation was aborted.", "AbortError"),
            );
          },
          { once: true },
        );
      }),
    startFileHash: (): FileHashTask => resolvedHashTask(),
  };

  const task = startBrowserFileUpload(
    { agentId: "agent-1", file: file() },
    uploadDependencies,
  );
  await Promise.resolve();
  task.cancel();

  await assert.rejects(task.promise, /aborted/);
  assert.equal(abortObserved, true);
});
