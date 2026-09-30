import assert from "node:assert/strict";
import test from "node:test";

void test("default upload transport preserves the global fetch receiver", async (context) => {
  const selectedFile = new File(["file-body"], "report.txt", {
    type: "text/plain",
  });
  const calls: { input: RequestInfo | URL; init?: RequestInit }[] = [];
  const responses = [
    Response.json({
      upload_id: "upload-1",
      put_url: "https://storage.example/opaque-signed-url",
      put_headers: { "Content-Type": "text/plain" },
      expires_at: "2026-09-30T12:00:00Z",
    }),
    new Response(null, { status: 204 }),
    Response.json({
      attachment_id: "attachment-1",
      uri: "exchange://attachment-1",
      media_type: "text/plain",
      size: selectedFile.size,
    }),
  ];
  context.mock.method(
    globalThis,
    "fetch",
    function (
      this: unknown,
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> {
      if (this !== globalThis) {
        throw new TypeError(
          "Can only call Window.fetch on instances of Window",
        );
      }
      calls.push({ input, init });
      const response = responses.shift();
      assert.ok(response, "Unexpected upload request");
      return Promise.resolve(response);
    },
  );

  class HashWorker {
    public onmessage:
      ((event: MessageEvent<{ type: "done"; sha256: string }>) => void) | null =
      null;

    public onerror: (() => void) | null = null;

    public postMessage(): void {
      this.onmessage?.(
        new MessageEvent("message", {
          data: { type: "done", sha256: "a".repeat(64) },
        }),
      );
    }

    public terminate(): void {}
  }

  const workerDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    "Worker",
  );
  Object.defineProperty(globalThis, "Worker", {
    configurable: true,
    value: HashWorker,
  });
  context.after((): void => {
    if (workerDescriptor) {
      Object.defineProperty(globalThis, "Worker", workerDescriptor);
    } else {
      Reflect.deleteProperty(globalThis, "Worker");
    }
  });

  const { startBrowserFileUpload } = await import("./browserFileUpload.ts");
  const uploaded = await startBrowserFileUpload({
    agentId: "agent-1",
    file: selectedFile,
  }).promise;

  assert.equal(uploaded.attachmentId, "attachment-1");
  assert.deepEqual(
    calls.map((call) => [call.input, call.init?.method]),
    [
      ["/api/chat/upload", "POST"],
      ["https://storage.example/opaque-signed-url", "PUT"],
      ["/api/chat/upload/upload-1/finalize", "POST"],
    ],
  );
  assert.equal(calls[1]?.init?.body, selectedFile);
});
