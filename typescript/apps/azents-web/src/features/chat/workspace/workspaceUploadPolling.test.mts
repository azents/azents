import assert from "node:assert/strict";
import test from "node:test";

import { pollWorkspaceUploadStatus } from "./workspaceUploadPolling.ts";

void test("uses a fresh server request for every lifecycle poll", async () => {
  const statuses = ["moving_to_runtime", "moving_to_runtime", "succeeded"];
  const requests: Array<{
    agentId: string;
    uploadId: string;
    staleTime: number;
  }> = [];
  const observed: string[] = [];

  const result = await pollWorkspaceUploadStatus({
    fetchStatus: (input, options) => {
      requests.push({ ...input, staleTime: options.staleTime });
      const status = statuses.shift();
      assert.ok(status);
      return Promise.resolve(status);
    },
    input: { agentId: "agent-1", uploadId: "upload-1" },
    isTerminal: (status) => status === "succeeded",
    onStatus: (status) => {
      observed.push(status);
    },
    wait: async () => {},
  });

  assert.equal(result, "succeeded");
  assert.deepEqual(observed, [
    "moving_to_runtime",
    "moving_to_runtime",
    "succeeded",
  ]);
  assert.deepEqual(requests, [
    { agentId: "agent-1", uploadId: "upload-1", staleTime: 0 },
    { agentId: "agent-1", uploadId: "upload-1", staleTime: 0 },
    { agentId: "agent-1", uploadId: "upload-1", staleTime: 0 },
  ]);
});

void test("continues cancellation polling until the cancelled terminal phase", async () => {
  const statuses = ["uploading", "moving_to_runtime", "cancelled"];
  const observed: string[] = [];

  const result = await pollWorkspaceUploadStatus({
    fetchStatus: () => {
      const status = statuses.shift();
      assert.ok(status);
      return Promise.resolve(status);
    },
    input: { agentId: "agent-1", uploadId: "upload-1" },
    isTerminal: (status) => status === "cancelled",
    onStatus: (status) => {
      observed.push(status);
    },
    wait: async () => {},
  });

  assert.equal(result, "cancelled");
  assert.deepEqual(observed, ["uploading", "moving_to_runtime", "cancelled"]);
});
