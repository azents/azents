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
      subject: "example.ts",
      qualifier: null,
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

void test("summarizes multiple patch files with the first filename", () => {
  const paths = [
    "/workspace/agent/src/bar.py",
    "/workspace/agent/src/one.py",
    "/workspace/agent/src/two.py",
    "/workspace/agent/src/three.py",
  ];
  const result = knownToolPresentation(
    toolCall({
      name: "apply_patch",
      arguments: JSON.stringify({
        base_path: "/workspace/agent",
        patch:
          "*** Begin Patch\n" +
          paths
            .map(
              (path, index) =>
                `*** Add File: ${path.replace("/workspace/agent/", "")}\n+value = ${index}`,
            )
            .join("\n") +
          "\n*** End Patch",
      }),
      resultMetadata: {
        kind: "apply_patch_result",
        changes: paths.toReversed().map((path) => ({
          action: "add",
          path,
          added_lines: 1,
          removed_lines: 0,
        })),
      },
    }),
  );
  assert.equal(result.type, "specialized");
  assert.equal(result.presentation.subject, "bar.py +3");
  assert.equal(result.presentation.qualifier, null);
});

void test("keeps patch summaries stable across terminal outcomes", () => {
  const argumentsText = JSON.stringify({
    base_path: "/workspace/agent",
    patch:
      "*** Begin Patch\n" +
      "*** Delete File: src/foo.py\n" +
      "*** Add File: src/bar.py\n" +
      "+value = 1\n" +
      "*** End Patch",
  });
  const cases: ActiveToolCall[] = [
    toolCall({
      name: "apply_patch",
      arguments: argumentsText,
      status: "running",
    }),
    toolCall({
      name: "apply_patch",
      arguments: argumentsText,
      resultMetadata: {
        kind: "apply_patch_result",
        changes: [],
      },
    }),
    toolCall({
      name: "apply_patch",
      arguments: argumentsText,
      status: "failed",
      resultMetadata: {
        kind: "apply_patch_failure",
        applied: [
          {
            action: "add",
            path: "/workspace/agent/src/bar.py",
            added_lines: 1,
            removed_lines: 0,
          },
        ],
      },
    }),
    toolCall({
      name: "apply_patch",
      arguments: argumentsText,
      status: "failed",
      resultMetadata: {
        kind: "apply_patch_failure",
        applied: [],
      },
    }),
  ];
  for (const item of cases) {
    const result = knownToolPresentation(item);
    assert.equal(result.type, "specialized");
    assert.equal(result.presentation.subject, "foo.py +1");
    assert.equal(result.presentation.qualifier, null);
  }
});

void test("specializes a plaintext custom apply_patch envelope", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "apply_patch",
      wireDialect: "plaintext_custom",
      arguments:
        "*** Base Path: /workspace/agent\n*** Begin Patch\n*** Add File: placeholder\n*** End Patch",
      resultMetadata: {
        kind: "apply_patch_result",
        changes: [
          {
            action: "add",
            path: "/workspace/agent/placeholder",
            added_lines: 0,
            removed_lines: 0,
          },
        ],
      },
    }),
  );
  assert.equal(result.type, "specialized");
  assert.equal(result.presentation.action, "patch");
  assert.equal(result.presentation.subject, "placeholder");
});

void test("rejects malformed plaintext custom apply_patch envelopes", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "apply_patch",
      wireDialect: "plaintext_custom",
      arguments: "*** Base Path: relative\n*** Begin Patch",
    }),
  );
  assert.deepEqual(result, { type: "generic", reason: "invalid-arguments" });
});

void test("rejects oversized plaintext custom apply_patch envelopes", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "apply_patch",
      wireDialect: "plaintext_custom",
      arguments: `*** Base Path: /workspace/agent\n${"x".repeat(1024 * 1024)}`,
    }),
  );
  assert.deepEqual(result, { type: "generic", reason: "invalid-arguments" });
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

void test("renders update_todo replacement as checklist detail", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "update_todo",
      arguments: JSON.stringify({
        operation: "replace",
        items: [
          { content: "Inspect CI", status: "completed" },
          { content: "Fix failures", status: "in_progress" },
          { content: "Create PR", status: "pending" },
        ],
      }),
      result: "Done",
      status: "completed",
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "updateTodo",
      subject: null,
      qualifier: "3",
      detail: {
        type: "todo",
        items: [
          { content: "Inspect CI", status: "completed" },
          { content: "Fix failures", status: "in_progress" },
          { content: "Create PR", status: "pending" },
        ],
      },
    },
  });
});

void test("renders update_todo clear without empty detail", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "update_todo",
      arguments: '{"operation":"clear"}',
      result: "Done",
      status: "completed",
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "updateTodo",
      subject: null,
      qualifier: "clear",
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
      name: "wait",
      arguments: '{"timeout_seconds":900}',
      action: "wait",
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

void test("rejects a runtime wait timeout over fifteen minutes", () => {
  assert.deepEqual(
    knownToolPresentation(
      toolCall({
        name: "wait",
        arguments: '{"timeout_seconds":901}',
        status: "running",
      }),
    ),
    { type: "generic", reason: "invalid-arguments" },
  );
});

void test("renders a completed runtime wait result", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "wait",
      arguments: '{"timeout_seconds":30}',
      result:
        '{"outcome":"activity","reason":"new user input, agent or subagent message"}',
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "wait",
      subject: null,
      qualifier: "activity",
      detail: {
        type: "semantic",
        fields: [{ label: "timeout", value: "30" }],
        sections: [
          {
            label: "result",
            content: "new user input, agent or subagent message",
          },
        ],
        items: [],
      },
    },
  });
});

void test("renders a completed managed Skill result", () => {
  const skillPath = "azents://skills/test/sample/SKILL.md";
  const content = [
    "---",
    "name: sample",
    "description: Test Skill",
    "---",
    "",
    "# Deep Research",
  ].join("\n");
  const metadata = {
    name: "sample",
    slug: "sample",
    skill_path: skillPath,
    source_kind: "azents",
    source_label: "test",
    relative_hint: "test/sample",
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
      subject: "sample",
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
        uri: "azents://skills/test/sample/references/checklist.md",
        path: "/tmp/agent/imports/checklist.md",
        overwrite: false,
      }),
      result: "Imported managed resource.",
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "importFile",
      subject: "checklist.md",
      qualifier: null,
      detail: {
        type: "semantic",
        fields: [
          { label: "source", value: "azents" },
          {
            label: "destination",
            value: "/tmp/agent/imports/checklist.md",
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

void test("specializes an accepted managed Git worktree creation request", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "create_git_worktree",
      arguments: JSON.stringify({
        source_project_path: "/workspace/agent/projects/azents",
        starting_ref: "main",
        branch_name: "feat/worktree-tools",
      }),
      result: JSON.stringify({
        accepted: true,
        message:
          "The worktree request was accepted. The authoritative result will arrive through a fresh continuation Run.",
        request_id: "request-create-1",
      }),
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "createGitWorktree",
      subject: "feat/worktree-tools",
      qualifier: null,
      detail: {
        type: "semantic",
        fields: [
          { label: "source", value: "/workspace/agent/projects/azents" },
          { label: "startingRef", value: "main" },
          { label: "branch", value: "feat/worktree-tools" },
          { label: "requestId", value: "request-create-1" },
        ],
        sections: [
          {
            label: "result",
            content:
              "The worktree request was accepted. The authoritative result will arrive through a fresh continuation Run.",
          },
        ],
        items: [],
      },
    },
  });
});

void test("specializes an accepted managed Git worktree removal request", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "remove_git_worktree",
      arguments: JSON.stringify({
        worktree_project_path:
          "/workspace/agent/sessions/session-1/worktrees/azents",
        force: false,
      }),
      result: JSON.stringify({
        accepted: true,
        message:
          "The worktree removal request was accepted. The authoritative result will arrive through a fresh continuation Run.",
        request_id: "request-remove-1",
      }),
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "removeGitWorktree",
      subject: "azents",
      qualifier: null,
      detail: {
        type: "semantic",
        fields: [
          {
            label: "worktreePath",
            value: "/workspace/agent/sessions/session-1/worktrees/azents",
          },
          { label: "force", value: "false" },
          { label: "requestId", value: "request-remove-1" },
        ],
        sections: [
          {
            label: "result",
            content:
              "The worktree removal request was accepted. The authoritative result will arrive through a fresh continuation Run.",
          },
        ],
        items: [],
      },
    },
  });
});

void test("renders a Scheduled Task creation without exposing the prompt collapsed", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "add_scheduled_task",
      arguments: JSON.stringify({
        title: "Daily report",
        objective: "Prepare the daily operating report.",
        at: null,
        cron: "0 9 * * 1-5",
        timezone: "America/New_York",
        channel_id: "opaque-channel-handle",
      }),
      toolkitSource: {
        toolkit_config_id: "scheduled",
        toolkit_type: "builtin",
        toolkit_name: "Scheduled Tasks",
        toolkit_slug: "scheduled",
      },
      result: JSON.stringify({
        task: {
          task_id: "t".repeat(32),
          title: "Daily report",
          objective: "Prepare the daily operating report.",
          at: null,
          cron: "0 9 * * 1-5",
          timezone: "America/New_York",
          channel_id: "opaque-channel-handle",
          next_eligible_at: "2026-08-18T13:00:00Z",
          pending_scheduled_for: null,
        },
        created: true,
        registration: null,
      }),
    }),
  );

  assert.equal(result.type, "specialized");
  assert.equal(result.presentation.action, "addScheduledTask");
  assert.equal(result.presentation.subject, "Daily report");
  assert.equal(result.presentation.qualifier, "recurring");
  assert.equal(
    JSON.stringify({
      action: result.presentation.action,
      subject: result.presentation.subject,
      qualifier: result.presentation.qualifier,
    }).includes("Prepare the daily operating report."),
    false,
  );
  assert.deepEqual(result.presentation.detail, {
    type: "semantic",
    fields: [
      {
        label: "schedule",
        value: "0 9 * * 1-5 · America/New_York",
      },
      { label: "target", value: "channel" },
      { label: "nextRun", value: "2026-08-18T13:00:00Z" },
    ],
    sections: [
      {
        label: "objective",
        content: "Prepare the daily operating report.",
      },
    ],
    items: [],
  });
});

void test("renders Scheduled Task list, delete, and terminal result operations", () => {
  const listed = knownToolPresentation(
    toolCall({
      name: "list_scheduled_tasks",
      arguments: "{}",
      result: JSON.stringify({
        tasks: [
          {
            task_id: "t".repeat(32),
            title: "Daily report",
            objective: "Prepare the report.",
            at: "2026-08-18T13:00:00Z",
            cron: null,
            timezone: null,
            channel_id: null,
            next_eligible_at: "2026-08-18T13:00:00Z",
            pending_scheduled_for: null,
            execution_state: "idle",
          },
        ],
      }),
    }),
  );
  const deleted = knownToolPresentation(
    toolCall({
      name: "delete_scheduled_task",
      arguments: JSON.stringify({ task_id: "t".repeat(32) }),
      result: JSON.stringify({ task_id: "t".repeat(32), deleted: true }),
    }),
  );
  const submitted = knownToolPresentation(
    toolCall({
      name: "submit_scheduled_task_result",
      arguments: JSON.stringify({
        status: "finished",
        result: "Completed.",
      }),
      result: JSON.stringify({
        status: "finished",
        result: "Completed.",
        recovered: false,
        outcomes: [],
      }),
    }),
  );

  assert.equal(listed.type, "specialized");
  assert.equal(listed.presentation.action, "listScheduledTasks");
  assert.equal(listed.presentation.qualifier, "1");
  assert.equal(deleted.type, "specialized");
  assert.equal(deleted.presentation.action, "deleteScheduledTask");
  assert.equal(deleted.presentation.qualifier, "deleted");
  assert.equal(submitted.type, "specialized");
  assert.equal(submitted.presentation.action, "submitScheduledTaskResult");
  assert.equal(submitted.presentation.qualifier, "finished");
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

void test("renders the canonical bounded list_agents contract", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "list_agents",
      arguments: "{}",
      result: JSON.stringify({
        agents: [
          { agent_name: "/root", agent_status: "running" },
          { agent_name: "/root/reviewer", agent_status: "completed" },
        ],
      }),
    }),
  );

  assert.deepEqual(result, {
    type: "specialized",
    presentation: {
      action: "listAgents",
      subject: null,
      qualifier: "2",
      detail: {
        type: "semantic",
        fields: [],
        sections: [],
        items: [
          {
            title: "/root",
            subtitle: "running",
            content: null,
          },
          {
            title: "/root/reviewer",
            subtitle: "completed",
            content: null,
          },
        ],
      },
    },
  });
});

void test("falls back for historical four-field list_agents results", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "list_agents",
      arguments: "{}",
      result: JSON.stringify({
        agents: [
          {
            agent_name: "reviewer",
            agent_path: "/root/reviewer",
            agent_status: "completed",
            last_task_message: "historical task preview",
          },
        ],
      }),
    }),
  );

  assert.deepEqual(result, { type: "generic", reason: "invalid-output" });
});

void test("falls back for malformed two-field list_agents results", () => {
  const result = knownToolPresentation(
    toolCall({
      name: "list_agents",
      arguments: "{}",
      result: JSON.stringify({
        agents: [{ agent_name: "/root/reviewer" }],
      }),
    }),
  );

  assert.deepEqual(result, { type: "generic", reason: "invalid-output" });
});
