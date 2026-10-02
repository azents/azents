import assert from "node:assert/strict";
import test from "node:test";
import {
  applyFunctionCallOutput,
  toolkitSourceFromValue,
} from "./toolCallMerge.ts";
import type { ChatMessage } from "../types.ts";

const message: ChatMessage = {
  id: "message-1",
  role: "assistant",
  content: null,
  createdAt: "2026-07-20T00:00:00.000Z",
  status: "complete",
  toolCalls: [
    {
      id: "call-1",
      callId: "call-1",
      name: "apply_patch",
      arguments: "{}",
      status: "running",
    },
  ],
};

void test("retains client result metadata on the matched tool call", () => {
  const metadata = {
    kind: "apply_patch_result",
    changes: [],
  };
  const messages = applyFunctionCallOutput([message], {
    callId: "call-1",
    content: "Applied patch.",
    attachments: [],
    metadata,
    status: "completed",
  });
  const toolCall = messages[0]?.toolCalls?.[0];
  assert.ok(toolCall);
  assert.equal(toolCall.status, "completed");
  assert.deepEqual(toolCall.resultMetadata, metadata);
});

void test("preserves malformed non-null Toolkit sources as non-specializable", () => {
  assert.deepEqual(
    toolkitSourceFromValue({
      toolkit_config_id: "toolkit-1",
      toolkit_type: "custom",
    }),
    { kind: "invalid" },
  );
  assert.equal(toolkitSourceFromValue(null), null);
});

void test("parses Foundation Toolkit namespace and safe identity metadata", () => {
  assert.deepEqual(
    toolkitSourceFromValue({
      toolkit_config_id: "toolkit-1",
      toolkit_type: "mcp",
      toolkit_name: "Production MCP",
      toolkit_slug: "mcp",
      toolkit_namespace: "mcp_2",
      source_identity: { server: "https://mcp.example" },
    }),
    {
      toolkit_config_id: "toolkit-1",
      toolkit_type: "mcp",
      toolkit_name: "Production MCP",
      toolkit_slug: "mcp",
      toolkit_namespace: "mcp_2",
      source_identity: { server: "https://mcp.example" },
    },
  );
});

void test("keeps historical Toolkit source snapshots readable", () => {
  assert.deepEqual(
    toolkitSourceFromValue({
      toolkit_config_id: "toolkit-1",
      toolkit_type: "mcp",
      toolkit_name: "Legacy MCP",
      toolkit_slug: "mcp",
    }),
    {
      toolkit_config_id: "toolkit-1",
      toolkit_type: "mcp",
      toolkit_name: "Legacy MCP",
      toolkit_slug: "mcp",
      toolkit_namespace: null,
      source_identity: {},
    },
  );
});
