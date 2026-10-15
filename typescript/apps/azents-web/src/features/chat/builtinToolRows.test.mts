import assert from "node:assert/strict";
import test from "node:test";
import { knownToolPresentation } from "./knownToolPresentation.ts";
import type { KnownToolAction } from "./knownToolPresentation.ts";
import type { ActiveToolCall } from "@azents/session-core/types";

const session = "a".repeat(32);
const event = "b".repeat(32);
const page = {
  id: "page-1",
  task_id: "task-1",
  resource_incarnation: "incarnation-1",
  url: "https://user:password@example.com/private?token=secret#secret",
};
function call(name: string, args: object, result: object): ActiveToolCall {
  return {
    id: name,
    name,
    arguments: JSON.stringify(args),
    result: JSON.stringify(result),
    status: "completed",
  };
}
const cases: Array<{ tool: ActiveToolCall; action: KnownToolAction }> = [
  {
    tool: call(
      "search_sessions",
      { query: "private query" },
      { sessions: [{ session_id: session, title: "Private Session title" }] },
    ),
    action: "searchSessions",
  },
  {
    tool: call(
      "search_sessions",
      { query: "private query", session_id: "current" },
      {
        session_id: session,
        matches: [
          {
            event_id: event,
            kind: "assistant_message",
            snippet: "Private snippet",
          },
        ],
      },
    ),
    action: "searchSessions",
  },
  {
    tool: call(
      "read_session_history",
      { session_id: session },
      {
        session_id: session,
        events: [
          {
            event_id: event,
            kind: "assistant_message",
            text: "Private history",
          },
        ],
      },
    ),
    action: "readSessionHistory",
  },
  {
    tool: call(
      "read_session_tool_result",
      { session_id: session, event_id: event },
      {
        session_id: session,
        event_id: event,
        tool: "read",
        text: "Private tool output",
        next_cursor: null,
      },
    ),
    action: "readSessionToolResult",
  },
  {
    tool: call(
      "download_external_file",
      { file: "opaque-private-locator", path: "/tmp/report.pdf" },
      {
        path: "/tmp/report.pdf",
        filename: "report.pdf",
        media_type: "application/pdf",
        bytes: 10,
      },
    ),
    action: "downloadExternalFile",
  },
  {
    tool: call("browser_open", { url: page.url }, { page, content: null }),
    action: "browserOpen",
  },
  {
    tool: call(
      "browser_observe",
      { task_id: "task-1", page_id: "page-1", view: "dom" },
      { page, content: "Private page content" },
    ),
    action: "browserObserve",
  },
  {
    tool: call(
      "browser_observe",
      { view: "status" },
      { page: null, content: null, tasks: [] },
    ),
    action: "browserObserve",
  },
  {
    tool: call(
      "browser_act",
      {
        task_id: "task-1",
        page_id: "page-1",
        resource_incarnation: "incarnation-1",
        action: "fill",
        text: "private password",
      },
      { page, content: null, action_state: "dispatched" },
    ),
    action: "browserAct",
  },
  {
    tool: call(
      "tool_search",
      { query: "private query" },
      {
        activated_tools: [],
        requested_limit: 5,
        activation_limit: null,
        limit_reduced: false,
      },
    ),
    action: "toolSearch",
  },
  {
    tool: call("list_web_services", {}, { items: [], total_count: 0 }),
    action: "runtimeWeb",
  },
];
for (const [mode, action] of Object.entries({
  continue: "channelContinue",
  finish: "channelFinish",
  request_input: "channelRequestInput",
  ignore: "channelIgnore",
} as const)) {
  cases.push({
    tool: call(
      "channel_action",
      {
        binding: "private-binding",
        mode,
        message: mode === "ignore" ? null : "private message",
      },
      { state: "finished", outcomes: [] },
    ),
    action,
  });
}

void test("specializes every added builtin and browser row across execution states", () => {
  for (const { tool, action } of cases) {
    for (const status of [
      "running",
      "completed",
      "failed",
      "cancelled",
    ] as const) {
      const presentation = knownToolPresentation({ ...tool, status });
      assert.equal(presentation.type, "specialized", `${tool.name} ${status}`);
      assert.equal(presentation.presentation.action, action);
    }
  }
});

void test("keeps private content out of collapsed summaries and strips browser URL credentials", () => {
  for (const { tool } of cases) {
    const result = knownToolPresentation(tool);
    assert.equal(result.type, "specialized");
    const summary = `${result.presentation.subject ?? ""} ${result.presentation.qualifier ?? ""}`;
    assert.doesNotMatch(
      summary,
      /private|Private|password|secret|token|opaque/,
    );
    if (tool.name === "browser_open" || tool.name === "browser_act") {
      assert.equal(result.presentation.subject, "example.com");
    }
  }
});

void test("does not reinterpret invalid payloads or Toolkit-owned names", () => {
  for (const name of [
    "read_session_history",
    "read_session_tool_result",
    "browser_act",
    "download_external_file",
    "channel_action",
  ]) {
    assert.equal(
      knownToolPresentation(call(name, {}, {})).type,
      "generic",
      name,
    );
  }
  for (const { tool } of cases) {
    assert.equal(
      knownToolPresentation({
        ...tool,
        toolkitSource: {
          toolkit_config_id: "external",
          toolkit_type: "mcp",
          toolkit_name: "External",
          toolkit_slug: "external",
        },
      }).type,
      "generic",
    );
  }
});
