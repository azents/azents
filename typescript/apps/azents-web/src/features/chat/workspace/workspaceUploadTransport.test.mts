import assert from "node:assert/strict";
import test from "node:test";

import {
  startWorkspaceUploadPut,
  type WorkspaceUploadPutInput,
} from "./workspaceUploadTransport.ts";

type Handler = (() => void) | null;

class FakeXmlHttpRequest {
  public static readonly DONE = 4;

  public static latest: FakeXmlHttpRequest | null = null;

  public constructor() {
    FakeXmlHttpRequest.latest = this;
  }

  public readonly upload: {
    onprogress:
      | ((event: {
          loaded: number;
          total: number;
          lengthComputable: boolean;
        }) => void)
      | null;
  } = { onprogress: null };

  public readyState = 0;

  public status = 0;

  public method = "";

  public url = "";

  public body: unknown = null;

  public aborted = false;

  public readonly headers: Record<string, string> = {};

  public onload: Handler = null;

  public onerror: Handler = null;

  public onabort: Handler = null;

  public open(method: string, url: string): void {
    this.method = method;
    this.url = url;
    this.readyState = 1;
  }

  public setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  public send(body: unknown): void {
    this.body = body;
    this.readyState = 2;
  }

  public abort(): void {
    this.aborted = true;
    this.readyState = FakeXmlHttpRequest.DONE;
    this.onabort?.();
  }

  public emitProgress(
    loaded: number,
    total: number,
    lengthComputable = true,
  ): void {
    this.upload.onprogress?.({ loaded, total, lengthComputable });
  }

  public respond(status: number): void {
    this.status = status;
    this.readyState = FakeXmlHttpRequest.DONE;
    this.onload?.();
  }

  public fail(): void {
    this.readyState = FakeXmlHttpRequest.DONE;
    this.onerror?.();
  }
}

const originalXmlHttpRequest = globalThis.XMLHttpRequest;

function start(inputOverrides: Partial<WorkspaceUploadPutInput> = {}) {
  globalThis.XMLHttpRequest =
    FakeXmlHttpRequest as unknown as typeof XMLHttpRequest;

  const file = new File(["hello"], "hello.txt", { type: "text/plain" });
  const progress: Array<[number, number]> = [];
  return {
    task: startWorkspaceUploadPut({
      url: "https://storage.example/upload",
      method: "PUT",
      headers: { "Content-Type": "text/plain" },
      file,
      onProgress: (loaded, total) => progress.push([loaded, total]),
      ...inputOverrides,
    }),
    file,
    progress,
  };
}

function currentRequest(): FakeXmlHttpRequest {
  const request = FakeXmlHttpRequest.latest;
  assert.ok(request);
  return request;
}

test.afterEach(() => {
  globalThis.XMLHttpRequest = originalXmlHttpRequest;
  FakeXmlHttpRequest.latest = null;
});

void test("sends a direct PUT with signed headers and reports progress", async () => {
  const { task, file, progress } = start();
  const request = currentRequest();
  assert.equal(request.method, "PUT");
  assert.equal(request.url, "https://storage.example/upload");
  assert.equal(request.headers["Content-Type"], "text/plain");
  assert.equal(request.body, file);

  request.emitProgress(2, file.size);
  request.respond(204);

  await task.promise;
  assert.deepEqual(progress, [
    [2, file.size],
    [file.size, file.size],
  ]);
});

void test("rejects non-success and network responses", async () => {
  const first = start();
  currentRequest().respond(503);
  await assert.rejects(first.task.promise, /Direct upload failed \(503\)/);

  const second = start();
  currentRequest().fail();
  await assert.rejects(second.task.promise, /storage request was unavailable/);
});

void test("aborts an in-flight direct PUT", async () => {
  const { task } = start();
  const request = currentRequest();
  task.abort();
  assert.equal(request.aborted, true);
  await assert.rejects(task.promise, /Direct upload was cancelled/);
});
