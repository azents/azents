import type {
  RoutineToolResult,
  RoutineWorkView,
} from "./routineToolPresentation.ts";
import type { RoutineToolName } from "@azents/session-core/routinePresentation";
import type { ActiveToolCall } from "@azents/session-core/types";

export const routineDefinitionFixture: Extract<
  RoutineToolResult,
  { type: "definition" }
>["definition"] = {
  id: "routine-a",
  slug: "traffic",
  scope: {
    workspace_id: "workspace-a",
    agent_id: "agent-a",
    session_id: "session-a",
  },
  content: {
    title: "Traffic anomalies",
    objective:
      "Inspect the approved traffic dashboard and investigate unusual changes.",
    sources: [{ type: "manual" }],
  },
  created_at: "2026-10-19T00:00:00Z",
  updated_at: "2026-10-19T00:00:00Z",
};
export const routineWorkFixture: RoutineWorkView = {
  objective_outcome: "finished",
  result: "Traffic remains within the normal range.",
  next_hint: "Compare the next observation with this baseline.",
  notify: false,
  message: null,
};
export const routineContextFixture: Extract<
  RoutineToolResult,
  { type: "context" }
>["context"] = {
  execution_id: "occurrence-a",
  judgment_id: "judgment-a",
  scope: routineDefinitionFixture.scope,
  candidate: {
    routine_id: routineDefinitionFixture.id,
    slug: routineDefinitionFixture.slug,
    content: routineDefinitionFixture.content,
    events: [{ source_type: "manual", observed_at: "2026-10-19T00:00:00Z" }],
    last_executed_at: null,
    latest_work: null,
  },
  admitted_at: "2026-10-19T00:00:00Z",
};
export const routineCompletionFixture: Extract<
  RoutineToolResult,
  { type: "completion" }
>["execution"] = {
  context: routineContextFixture,
  phase: "completed",
  current_run_id: "run-a",
  started_at: "2026-10-19T00:01:00Z",
  completed_at: "2026-10-19T00:03:00Z",
  work: routineWorkFixture,
  delivery_status: "not_requested",
  delivery_error: null,
};

export function routineCallFixture(
  name: RoutineToolName,
  input: unknown,
  status: ActiveToolCall["status"],
  result: unknown,
): ActiveToolCall {
  const argumentsText = JSON.stringify(input);
  const resultText = result === null ? null : JSON.stringify(result);
  if (
    typeof argumentsText !== "string" ||
    (result !== null && typeof resultText !== "string")
  ) {
    throw new Error("Routine fixture must contain JSON values");
  }
  return {
    id: `call-${name}`,
    callId: `call-${name}`,
    name,
    arguments: argumentsText,
    wireDialect: "json_function",
    status,
    toolkitSource: null,
    ...(typeof resultText === "string" ? { result: resultText } : {}),
  };
}
