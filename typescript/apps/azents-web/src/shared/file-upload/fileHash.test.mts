import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { type FileHashTask, startFileHash } from "./fileHash.ts";

type HashReply =
  | { type: "progress"; loadedBytes: number; totalBytes: number }
  | { type: "done"; sha256: string };

class MockWorker {
  readonly url: URL;
  readonly options: WorkerOptions;
  readonly messages: { file: File }[] = [];
  terminationCount = 0;
  onmessage: ((event: MessageEvent<HashReply>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: URL, options: WorkerOptions) {
    this.url = url;
    this.options = options;
  }

  postMessage(message: { file: File }): void {
    this.messages.push(message);
  }

  terminate(): void {
    this.terminationCount++;
  }

  reply(data: HashReply): void {
    this.onmessage?.(new MessageEvent<HashReply>("message", { data }));
  }

  fail(): void {
    this.onerror?.(new Event("error"));
  }
}

interface WorkerHarness {
  workers: MockWorker[];
  start: (
    file: File,
    progress: (loadedBytes: number, totalBytes: number) => void,
  ) => FileHashTask;
}

function mockWorkers(context: TestContext): WorkerHarness {
  const workers: MockWorker[] = [];
  const tasks: FileHashTask[] = [];
  const previous = Object.getOwnPropertyDescriptor(globalThis, "Worker");

  class CapturedWorker extends MockWorker {
    constructor(url: URL, options: WorkerOptions) {
      super(url, options);
      workers.push(this);
    }
  }

  Object.defineProperty(globalThis, "Worker", {
    configurable: true,
    value: CapturedWorker,
  });
  context.after(async (): Promise<void> => {
    try {
      await Promise.allSettled(
        tasks.map((task): Promise<string> => {
          task.cancel();
          return task.promise;
        }),
      );
    } finally {
      if (previous) {
        Object.defineProperty(globalThis, "Worker", previous);
      } else {
        Reflect.deleteProperty(globalThis, "Worker");
      }
    }
  });
  return {
    workers,
    start: (
      file: File,
      progress: (loadedBytes: number, totalBytes: number) => void,
    ): FileHashTask => {
      const task = startFileHash(file, progress);
      tasks.push(task);
      return task;
    },
  };
}

function firstWorker(harness: WorkerHarness): MockWorker {
  const worker = harness.workers[0];
  assert.ok(worker, "Expected one dedicated hashing Worker.");
  return worker;
}

function selectedFile(): File {
  return new File(["file-body"], "report.txt", { type: "text/plain" });
}

void test("starts a dedicated module Worker with the original File", async (context): Promise<void> => {
  const harness = mockWorkers(context);
  const file = selectedFile();
  const task = harness.start(file, (): void => {});
  const worker = firstWorker(harness);

  assert.equal(harness.workers.length, 1);
  assert.ok(worker.url instanceof URL);
  assert.equal(
    worker.url.href,
    new URL("./fileHash.worker.ts", import.meta.url).href,
  );
  assert.deepEqual(worker.options, { type: "module" });
  assert.equal(worker.messages.length, 1);
  assert.equal(worker.messages[0]?.file, file);
  assert.equal(worker.terminationCount, 0);

  worker.reply({ type: "done", sha256: "a".repeat(64) });
  await task.promise;
});

void test("forwards Worker progress without terminating the pending task", async (context): Promise<void> => {
  const harness = mockWorkers(context);
  const progress: { loadedBytes: number; totalBytes: number }[] = [];
  const task = harness.start(
    selectedFile(),
    (loadedBytes, totalBytes): void => {
      progress.push({ loadedBytes, totalBytes });
    },
  );
  const worker = firstWorker(harness);

  worker.reply({ type: "progress", loadedBytes: 3, totalBytes: 9 });
  worker.reply({ type: "progress", loadedBytes: 9, totalBytes: 9 });
  assert.deepEqual(progress, [
    { loadedBytes: 3, totalBytes: 9 },
    { loadedBytes: 9, totalBytes: 9 },
  ]);
  assert.equal(worker.terminationCount, 0);

  worker.reply({ type: "done", sha256: "b".repeat(64) });
  await task.promise;
});

void test("resolves the completed checksum and terminates exactly once", async (context): Promise<void> => {
  const harness = mockWorkers(context);
  const task = harness.start(selectedFile(), (): void => {});
  const worker = firstWorker(harness);
  const digest = "c".repeat(64);

  worker.reply({ type: "done", sha256: digest });
  assert.equal(await task.promise, digest);
  assert.equal(worker.terminationCount, 1);
  task.cancel();
  task.cancel();
  assert.equal(worker.terminationCount, 1);
});

void test("rejects a Worker error and releases the Worker", async (context): Promise<void> => {
  const harness = mockWorkers(context);
  const task = harness.start(selectedFile(), (): void => {});
  const worker = firstWorker(harness);
  const rejected = assert.rejects(
    task.promise,
    /Could not prepare the file checksum\./,
  );

  worker.fail();
  await rejected;
  assert.equal(worker.terminationCount, 1);
  task.cancel();
  assert.equal(worker.terminationCount, 1);
});

void test("cancellation rejects pending work and is idempotent", async (context): Promise<void> => {
  const harness = mockWorkers(context);
  const task = harness.start(selectedFile(), (): void => {});
  const worker = firstWorker(harness);
  const rejected = assert.rejects(
    task.promise,
    /File checksum preparation was cancelled\./,
  );

  task.cancel();
  task.cancel();
  await rejected;
  assert.equal(worker.terminationCount, 1);
});
