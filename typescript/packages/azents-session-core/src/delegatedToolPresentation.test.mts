import assert from "node:assert/strict";
import test from "node:test";
import {
  delegatedToolFromValue,
  outputFileState,
  toolCallForDisplay,
} from "./delegatedToolPresentation.ts";
import { projectChatPresentationItems } from "./toolActivityPresentation.ts";
import type { ActiveToolCall } from "./types.ts";

const wrapper: ActiveToolCall = {
  id: "call",
  name: "run_tool_to_file",
  status: "completed",
  arguments: JSON.stringify({
    tool_name: "read",
    arguments: '{"path":"/tmp/result.txt"}',
    directory: "/tmp/output",
  }),
  delegatedTool: {
    name: "read",
    wireDialect: "json_function",
    toolkitSource: null,
  },
  result: "Ran read and stored output",
  resultMetadata: {
    failed_part_count: 0,
    manifest_stored: true,
    delegated_result: { output: "Target output", metadata: { target: true } },
  },
};

void test("delegates display fields while preserving canonical wrapper and lifecycle", () => {
  const displayed = toolCallForDisplay(wrapper);
  assert.equal(displayed.name, "read");
  assert.equal(displayed.arguments, '{"path":"/tmp/result.txt"}');
  assert.equal(displayed.result, "Target output");
  assert.deepEqual(displayed.resultMetadata, { target: true });
  assert.equal(displayed.status, wrapper.status);
  assert.equal(wrapper.name, "run_tool_to_file");
  assert.equal(outputFileState(wrapper), "stored");
  assert.equal(outputFileState(displayed), null);
});

void test("requires authoritative matching provenance and rejects malformed or recursive calls", () => {
  for (const call of [
    { ...wrapper, arguments: "{" },
    {
      ...wrapper,
      arguments: '{"tool_name":"run_tool_to_file","arguments":"{}"}',
    },
    { ...wrapper, delegatedTool: null },
    {
      ...wrapper,
      delegatedTool: {
        ...wrapper.delegatedTool,
        name: "another",
        wireDialect: "json_function",
        toolkitSource: null,
      },
    },
  ] satisfies ActiveToolCall[]) {
    assert.equal(toolCallForDisplay(call), call);
  }
  for (const value of [
    null,
    {},
    { name: "read", wire_dialect: "invalid" },
    { name: "run_tool_to_file", wire_dialect: "json_function" },
  ]) {
    assert.equal(delegatedToolFromValue(value), null);
  }
});

void test("preserves plaintext target dialect and explicit Toolkit identity", () => {
  const toolkitSource = {
    toolkit_config_id: "config",
    toolkit_type: "mcp",
    toolkit_name: "Research",
    toolkit_slug: "research",
  };
  const snapshot = delegatedToolFromValue({
    name: "target__search",
    wire_dialect: "plaintext_custom",
    toolkit_source: toolkitSource,
  });
  assert.ok(snapshot);
  const displayed = toolCallForDisplay({
    ...wrapper,
    arguments: JSON.stringify({
      tool_name: snapshot.name,
      arguments: "plain target input",
    }),
    delegatedTool: snapshot,
  });
  assert.equal(displayed.wireDialect, "plaintext_custom");
  assert.equal(displayed.arguments, "plain target input");
  assert.deepEqual(displayed.toolkitSource, snapshot.toolkitSource);
  assert.ok(
    displayed.toolkitSource && "toolkit_config_id" in displayed.toolkitSource,
  );
  assert.equal(displayed.toolkitSource.toolkit_config_id, "config");
});

void test("reports pending, failed, and partial storage without inventing success", () => {
  assert.equal(outputFileState({ ...wrapper, status: "running" }), "pending");
  assert.equal(outputFileState({ ...wrapper, status: "failed" }), "failed");
  assert.equal(
    outputFileState({
      ...wrapper,
      resultMetadata: { failed_part_count: 1, manifest_stored: true },
    }),
    "partial",
  );
  assert.equal(
    outputFileState({
      ...wrapper,
      resultMetadata: { failed_part_count: 0, manifest_stored: false },
    }),
    "partial",
  );
});

void test("Activity categorization follows builtin and Toolkit targets", () => {
  const cases: Array<{ call: ActiveToolCall; key: string }> = [
    { call: wrapper, key: "explore" },
    {
      call: {
        ...wrapper,
        delegatedTool: {
          ...wrapper.delegatedTool,
          name: "read",
          wireDialect: "json_function",
          toolkitSource: {
            toolkit_config_id: "config",
            toolkit_type: "mcp",
            toolkit_name: "Research",
            toolkit_slug: "research",
          },
        },
      },
      key: "toolkit:config",
    },
  ];
  for (const { call, key } of cases) {
    const items = projectChatPresentationItems(
      [
        {
          id: "event",
          session_id: "session",
          kind: "client_tool_call",
          payload: { call_id: "call" },
          external_id: null,
          adapter: null,
          provider: null,
          model: null,
          native_format: null,
          schema_version: "1",
          created_at: "2026-10-15T00:00:00Z",
        },
      ],
      [
        {
          id: "message",
          role: "assistant",
          content: null,
          createdAt: "2026-10-15T00:00:00Z",
          status: "complete",
          toolCalls: [call],
        },
      ],
    );
    const item = items[0];
    assert.equal(item?.type, "activity");
    if (item?.type === "activity") {
      assert.equal(item.activity.events[0]?.category?.key, key);
    }
  }
});
