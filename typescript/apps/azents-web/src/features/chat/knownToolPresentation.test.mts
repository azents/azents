import assert from "node:assert/strict";
import test from "node:test";
import { knownToolPresentation } from "./knownToolPresentation.ts";
import type { ActiveToolCall } from "./types.ts";

function toolCall(overrides: Partial<ActiveToolCall>): ActiveToolCall {
  return {
    id: "call-1",
    name: "read",
    arguments: '{"path":"/workspace/agent/src/example.ts"}',
    status: "completed",
    result: "export const example = true;",
    ...overrides,
  };
}

void test("specializes a validated first-party read call", () => {
  assert.deepEqual(knownToolPresentation(toolCall({})), {
    type: "specialized",
    presentation: {
      action: "read",
      subject: "src/example.ts",
      qualifier: null,
      detail: { type: "output", output: "export const example = true;" },
    },
  });
});

void test("keeps Toolkit-owned name collisions generic", () => {
  const result = knownToolPresentation(
    toolCall({
      toolkitSource: {
        toolkit_config_id: "toolkit-1",
        toolkit_type: "custom",
        toolkit_name: "Custom",
        toolkit_slug: "custom",
      },
    }),
  );
  assert.deepEqual(result, { type: "generic", reason: "unregistered" });
});

void test("keeps malformed non-null Toolkit source collisions generic", () => {
  const result = knownToolPresentation(
    toolCall({ toolkitSource: { kind: "invalid" } }),
  );
  assert.deepEqual(result, { type: "generic", reason: "unregistered" });
});

void test("keeps malformed registered arguments generic", () => {
  const result = knownToolPresentation(toolCall({ arguments: "not json" }));
  assert.deepEqual(result, { type: "generic", reason: "invalid-arguments" });
});

void test("requires structured metadata for terminal patch calls", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "apply_patch",
      arguments: '{"base_path":"/workspace/agent","patch":"*** Begin Patch"}',
    }),
  );
  assert.deepEqual(result, { type: "generic", reason: "invalid-output" });
});

void test("specializes structured patch metadata without parsing output text", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "apply_patch",
      arguments: '{"base_path":"/workspace/agent","patch":"*** Begin Patch"}',
      resultMetadata: {
        kind: "apply_patch_result",
        changes: [
          {
            action: "update",
            path: "/workspace/agent/src/example.ts",
            added_lines: 4,
            removed_lines: 2,
          },
        ],
      },
    }),
  );
  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "patch",
      subject: "agent",
      qualifier: "1",
      detail: {
        type: "patch",
        changes: [
          {
            action: "update",
            path: "src/example.ts",
            addedLines: 4,
            removedLines: 2,
          },
        ],
      },
    },
  });
});

void test("uses validated process metadata for terminal command detail", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "exec_command",
      arguments: '{"command":"pnpm test"}',
      result: "status: completed\n\nstdout:\nPassed",
      resultMetadata: {
        kind: "exec_command_result",
        status: "completed",
        exit_code: 0,
        stdout_truncated: false,
        stderr_truncated: false,
      },
    }),
  );
  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "command",
      subject: null,
      qualifier: "0",
      detail: {
        type: "process",
        exitCode: 0,
        truncated: false,
        output: "status: completed\n\nstdout:\nPassed",
      },
    },
  });
});

void test("normalizes specialized subjects to one bounded line", () => {
  const path = `/workspace/agent/src/with\ncontrol/${"a".repeat(120)}.ts`;
  const result = knownToolPresentation(
    toolCall({
      arguments: JSON.stringify({ path }),
    }),
  );
  assert.equal(result.type, "specialized");
  assert.ok(result.presentation.subject !== null);
  assert.equal(result.presentation.subject.includes("\n"), false);
  assert.ok(result.presentation.subject.length <= 96);
});

void test("specializes simple Phase 1 resource and search tools", () => {
  const cases: Array<{
    action: string;
    arguments: string;
    name: string;
  }> = [
    {
      name: "grep",
      arguments: '{"pattern":"ToolCall","path":"/workspace/agent/src"}',
      action: "search",
    },
    {
      name: "glob",
      arguments: '{"pattern":"/workspace/agent/src/**/*.ts"}',
      action: "list",
    },
    {
      name: "write",
      arguments: '{"path":"/workspace/agent/report.txt","content":"private"}',
      action: "write",
    },
    {
      name: "edit",
      arguments:
        '{"path":"/workspace/agent/report.txt","old_string":"old","new_string":"new"}',
      action: "edit",
    },
    {
      name: "delete",
      arguments: '{"path":"/workspace/agent/report.txt"}',
      action: "delete",
    },
  ];
  for (const item of cases) {
    const result = knownToolPresentation(
      toolCall({ name: item.name, arguments: item.arguments }),
    );
    assert.equal(result.type, "specialized");
    assert.equal(result.presentation.action, item.action);
  }
});

void test("keeps malformed process metadata generic and supports running stdin", () => {
  const malformed = knownToolPresentation(
    toolCall({
      name: "exec_command",
      arguments: '{"command":"pnpm test"}',
      resultMetadata: { kind: "other" },
    }),
  );
  assert.deepEqual(malformed, { type: "generic", reason: "invalid-output" });

  const mismatchedKind = knownToolPresentation(
    toolCall({
      name: "exec_command",
      arguments: '{"command":"pnpm test"}',
      resultMetadata: {
        kind: "write_stdin_result",
        status: "completed",
        exit_code: 0,
        stdout_truncated: false,
        stderr_truncated: false,
      },
    }),
  );
  assert.deepEqual(mismatchedKind, {
    type: "generic",
    reason: "invalid-output",
  });

  const running = knownToolPresentation(
    toolCall({
      name: "write_stdin",
      arguments: '{"process_id":"process-1"}',
      status: "running",
    }),
  );
  assert.deepEqual(running, {
    type: "specialized",
    presentation: {
      action: "process",
      subject: null,
      qualifier: null,
      detail: null,
    },
  });
});
