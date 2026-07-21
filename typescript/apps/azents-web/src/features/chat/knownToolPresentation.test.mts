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
      subject: "example.ts",
      qualifier: null,
      detail: {
        type: "output",
        output: "export const example = true;",
        language: "typescript",
      },
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
      arguments:
        '{"base_path":"/workspace/agent","patch":"*** Begin Patch\\n*** Update File: src/example.ts\\n@@\\n-old\\n+new\\n*** End Patch"}',
    }),
  );
  assert.deepEqual(result, { type: "generic", reason: "invalid-output" });
});

void test("specializes structured patch metadata without parsing output text", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "apply_patch",
      arguments:
        '{"base_path":"/workspace/agent","patch":"*** Begin Patch\\n*** Update File: src/example.ts\\n@@\\n-old\\n+new\\n*** End Patch"}',
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
        files: [
          {
            type: "update",
            path: "src/example.ts",
            moveTo: null,
            hunks: [
              {
                context: null,
                lines: [
                  { type: "remove", content: "old" },
                  { type: "add", content: "new" },
                ],
              },
            ],
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
        command: "pnpm test",
        exitCode: 0,
        truncated: false,
        output: "status: completed\n\nstdout:\nPassed",
      },
    },
  });
});

void test("uses the basename for file operation subjects", () => {
  const path = `/workspace/agent/src/with\ncontrol/${"a".repeat(120)}.ts`;
  const result = knownToolPresentation(
    toolCall({
      arguments: JSON.stringify({ path }),
    }),
  );
  assert.equal(result.type, "specialized");
  assert.equal(result.presentation.subject, `${"a".repeat(120)}.ts`);
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
      action: "grep",
    },
    {
      name: "glob",
      arguments: '{"pattern":"/workspace/agent/src/**/*.ts"}',
      action: "glob",
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

void test("renders file edits as a unified diff", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "edit",
      arguments:
        '{"path":"/workspace/agent/src/example.ts","old_string":"const value = 1;","new_string":"const value = 2;"}',
    }),
  );
  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "edit",
      subject: "example.ts",
      qualifier: null,
      detail: {
        type: "diff",
        file: {
          type: "update",
          path: "/workspace/agent/src/example.ts",
          moveTo: null,
          hunks: [
            {
              context: null,
              lines: [
                { type: "remove", content: "const value = 1;" },
                { type: "add", content: "const value = 2;" },
              ],
            },
          ],
        },
      },
    },
  });
});

void test("projects written file contents with inferred language", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "write",
      arguments:
        '{"path":"/workspace/agent/src/example.py","content":"value = True"}',
      result: "File written.",
    }),
  );
  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "write",
      subject: "example.py",
      qualifier: null,
      detail: {
        type: "output",
        output: "value = True",
        language: "python",
      },
    },
  });
});

void test("chooses a supported language for ambiguous file extensions", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "read",
      arguments: '{"path":"/workspace/agent/src/example.rs"}',
      result: "fn main() {}",
    }),
  );
  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "read",
      subject: "example.rs",
      qualifier: null,
      detail: {
        type: "output",
        output: "fn main() {}",
        language: "rust",
      },
    },
  });
});

void test("keeps malformed process metadata generic and shows running commands", () => {
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
      name: "exec_command",
      arguments: '{"command":"pnpm dev"}',
      status: "running",
    }),
  );
  assert.deepEqual(running, {
    type: "specialized",
    presentation: {
      action: "command",
      subject: null,
      qualifier: null,
      detail: {
        type: "process",
        command: "pnpm dev",
        exitCode: null,
        truncated: false,
        output: "",
      },
    },
  });
});

void test("specializes present_file with the first presented file", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "present_file",
      arguments:
        '{"paths":["/workspace/agent/reports/review.md","/workspace/agent/reports/preview.png"]}',
    }),
  );
  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "present",
      subject: "review.md",
      qualifier: null,
      detail: null,
    },
  });
});

void test("covers every remaining source-less builtin with a validated adapter", () => {
  const cases: Array<{
    action: string;
    arguments: string;
    name: string;
  }> = [
    {
      name: "read_image",
      arguments: '{"path":"/workspace/agent/chart.png"}',
      action: "readImage",
    },
    {
      name: "import_file",
      arguments:
        '{"uri":"exchange://file/report.csv","path":"/workspace/agent/report.csv"}',
      action: "importFile",
    },
    {
      name: "save_memory",
      arguments:
        '{"scope":"user","type":"feedback","name":"style","description":"Concise","content":"Use concise answers."}',
      action: "saveMemory",
    },
    {
      name: "list_memories",
      arguments: '{"scope":"agent","type":"project"}',
      action: "listMemories",
    },
    {
      name: "get_memory",
      arguments: '{"scope":"agent","name":"project"}',
      action: "getMemory",
    },
    {
      name: "search_memories",
      arguments: '{"query":"project rules","scope":"agent"}',
      action: "searchMemories",
    },
    {
      name: "delete_memory",
      arguments: '{"scope":"user","name":"style"}',
      action: "deleteMemory",
    },
    { name: "get_goal", arguments: "{}", action: "getGoal" },
    {
      name: "create_goal",
      arguments: '{"objective":"Ship the presentation"}',
      action: "createGoal",
    },
    {
      name: "update_goal",
      arguments: '{"status":"complete"}',
      action: "updateGoal",
    },
    {
      name: "update_todo",
      arguments:
        '{"operation":"replace","items":[{"content":"Implement","status":"in_progress"}]}',
      action: "updateTodo",
    },
    {
      name: "load_skill",
      arguments:
        '{"skill_path":"/workspace/agent/.azents/skills/review/SKILL.md"}',
      action: "loadSkill",
    },
    {
      name: "spawn_agent",
      arguments: '{"name":"reviewer","task":"Review the change"}',
      action: "spawnAgent",
    },
    {
      name: "send_message",
      arguments: '{"agent_name":"reviewer","message":"Check the UI"}',
      action: "sendMessage",
    },
    {
      name: "followup_task",
      arguments: '{"agent_name":"reviewer","task":"Recheck mobile"}',
      action: "followupTask",
    },
    {
      name: "wait_agent",
      arguments: '{"timeout_seconds":30}',
      action: "waitAgent",
    },
    {
      name: "interrupt_agent",
      arguments: '{"agent_name":"reviewer"}',
      action: "interruptAgent",
    },
    { name: "list_agents", arguments: "{}", action: "listAgents" },
    {
      name: "tool_search",
      arguments: '{"query":"search GitHub issues","limit":5}',
      action: "toolSearch",
    },
  ];

  for (const item of cases) {
    const result = knownToolPresentation(
      toolCall({
        name: item.name,
        arguments: item.arguments,
        status: "running",
      }),
    );
    assert.equal(result.type, "specialized", item.name);
    assert.equal(result.presentation.action, item.action, item.name);
  }
});

void test("renders a completed managed Skill result", () => {
  const skillPath = "azents://skills/azents/deep-research/SKILL.md";
  const content = [
    "---",
    "name: deep-research",
    "description: Research deeply",
    "---",
    "",
    "# Deep Research",
  ].join("\n");
  const metadata = {
    name: "deep-research",
    slug: "deep-research",
    skill_path: skillPath,
    source_kind: "azents",
    source_label: "azents",
    relative_hint: "azents/deep-research",
    projection_revision_id: "revision-1",
    projection_hash: "projection-hash",
    source_id: "global",
    source_revision_id: "release-1",
    content_hash: "content-hash",
  };
  const result = knownToolPresentation(
    toolCall({
      name: "load_skill",
      arguments: JSON.stringify({ skill_path: skillPath }),
      result: `Skill loaded from the active projection.\nMetadata: ${JSON.stringify(metadata)}\n\n${content}`,
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "loadSkill",
      subject: "deep-research",
      qualifier: null,
      detail: { type: "skill", content },
    },
  });
});

void test("renders an azents VFS import as a managed temporary file", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "import_file",
      arguments: JSON.stringify({
        uri: "azents://skills/azents/deep-research/references/evidence-checklist.md",
        path: "/tmp/agent/imports/evidence-checklist.md",
        overwrite: false,
      }),
      result: "Imported managed resource.",
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "importFile",
      subject: "evidence-checklist.md",
      qualifier: null,
      detail: {
        type: "semantic",
        fields: [
          { label: "source", value: "azents" },
          {
            label: "destination",
            value: "/tmp/agent/imports/evidence-checklist.md",
          },
          { label: "overwrite", value: "false" },
          { label: "temporary", value: "true" },
        ],
        sections: [],
        items: [],
      },
    },
  });
});

void test("keeps sensitive builtin payloads out of collapsed summaries", () => {
  const cases = [
    {
      name: "glob",
      arguments: '{"pattern":"/workspace/private/**/*.key"}',
      sensitive: "/workspace/private/**/*.key",
    },
    {
      name: "save_memory",
      arguments:
        '{"scope":"user","type":"feedback","name":"style","description":"Concise","content":"secret memory body"}',
      sensitive: "secret memory body",
    },
    {
      name: "create_goal",
      arguments: '{"objective":"secret goal objective"}',
      sensitive: "secret goal objective",
    },
    {
      name: "update_todo",
      arguments:
        '{"operation":"replace","items":[{"content":"secret todo item","status":"in_progress"}]}',
      sensitive: "secret todo item",
    },
    {
      name: "spawn_agent",
      arguments:
        '{"name":"reviewer","task":"secret task body","fork_turns":"none"}',
      sensitive: "secret task body",
    },
    {
      name: "send_message",
      arguments: '{"agent_name":"reviewer","message":"secret agent message"}',
      sensitive: "secret agent message",
    },
    {
      name: "tool_search",
      arguments: '{"query":"secret capability query"}',
      sensitive: "secret capability query",
    },
  ];

  for (const item of cases) {
    const result = knownToolPresentation(
      toolCall({
        name: item.name,
        arguments: item.arguments,
        status: "running",
      }),
    );
    assert.equal(result.type, "specialized", item.name);
    const collapsed = JSON.stringify({
      action: result.presentation.action,
      subject: result.presentation.subject,
      qualifier: result.presentation.qualifier,
    });
    assert.equal(collapsed.includes(item.sensitive), false, item.name);
  }
});

void test("falls back locally when a structured builtin result drifts", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "tool_search",
      arguments: '{"query":"GitHub tools"}',
      result: '{"unexpected":true}',
      status: "completed",
    }),
  );
  assert.deepEqual(result, { type: "generic", reason: "invalid-output" });
});
