import assert from "node:assert/strict";
import test from "node:test";
import { knownToolPresentation } from "./knownToolPresentation.ts";
import {
  routineCallFixture,
  routineCompletionFixture,
  routineContextFixture,
  routineDefinitionFixture,
  routineWorkFixture,
} from "./routineToolFixtures.ts";
import { toolCallActionMessageKey } from "./toolCallActionPresentation.ts";
import type {
  RoutineToolAction,
  RoutineToolDetail,
  RoutineWorkView,
} from "./routineToolPresentation.ts";
import type { ActiveToolCall } from "@azents/session-core/types";

function detail(call: ActiveToolCall): RoutineToolDetail {
  const projected = knownToolPresentation(call);
  if (
    projected.type !== "specialized" ||
    projected.presentation.detail?.type !== "routine"
  ) {
    throw new Error("Expected Routine semantic details");
  }
  return projected.presentation.detail;
}

void test("all seven Routine actions use semantic input/output and title or slug", () => {
  const cases = [
    routineCallFixture(
      "create_routine",
      routineDefinitionFixture.content,
      "completed",
      routineDefinitionFixture,
    ),
    routineCallFixture("list_routines", {}, "completed", {
      routines: [routineDefinitionFixture],
    }),
    routineCallFixture(
      "inspect_routine",
      { slug: "traffic", record_limit: 100 },
      "completed",
      { routine: { definition: routineDefinitionFixture, records: [] } },
    ),
    routineCallFixture(
      "update_routine",
      {
        slug: "traffic",
        expected: routineDefinitionFixture.content,
        changes: {},
      },
      "completed",
      routineDefinitionFixture,
    ),
    routineCallFixture("delete_routine", { slug: "traffic" }, "completed", {
      deleted: true,
      routine: routineDefinitionFixture,
    }),
    routineCallFixture(
      "read_routine_context",
      { slug: "traffic", execution_id: "occurrence-a" },
      "completed",
      routineContextFixture,
    ),
    routineCallFixture(
      "record_routine_result",
      {
        slug: "traffic",
        execution_id: "occurrence-a",
        work: routineWorkFixture,
      },
      "completed",
      { created: true, execution: routineCompletionFixture },
    ),
  ];
  const actions: RoutineToolAction[] = [
    "createRoutine",
    "listRoutines",
    "inspectRoutine",
    "updateRoutine",
    "deleteRoutine",
    "readRoutineContext",
    "recordRoutineResult",
  ];
  for (const [index, call] of cases.entries()) {
    const projected = knownToolPresentation(call);
    assert.equal(projected.type, "specialized");
    assert.equal(projected.presentation.action, actions[index]);
    assert.equal(
      projected.presentation.subject,
      call.name === "list_routines" ? null : "Traffic anomalies",
    );
    assert.equal(detail(call).outcome.type, "COMPLETED");
  }
});

void test("updates keep exact prior content, requested fields and actual output separate", () => {
  const expected = {
    ...routineDefinitionFixture.content,
    title: "  Original title  ",
  };
  const changes = { title: "Actual updated title" };
  const result = {
    ...routineDefinitionFixture,
    content: { ...expected, ...changes },
  };
  const call = routineCallFixture(
    "update_routine",
    { slug: "traffic", expected, changes },
    "completed",
    result,
  );
  const projected = detail(call);
  assert.equal(projected.request?.type, "updateRoutine");
  assert.deepEqual(projected.request.expected, expected);
  assert.deepEqual(projected.request.changes, changes);
  assert.equal(projected.outcome.type, "COMPLETED");
  assert.deepEqual(
    knownToolPresentation({
      ...call,
      result: JSON.stringify({ ...result, content: expected }),
    }),
    { type: "generic", reason: "invalid-output" },
  );
  assert.deepEqual(
    knownToolPresentation({
      ...call,
      result: JSON.stringify({ status: "conflict" }),
    }),
    { type: "generic", reason: "invalid-output" },
  );
});

void test("failed, cancelled and interrupted updates never receive successful mutation copy", () => {
  for (const status of ["failed", "cancelled", "interrupted"] as const) {
    const call = routineCallFixture(
      "update_routine",
      {
        slug: "traffic",
        expected: routineDefinitionFixture.content,
        changes: { title: "Requested new title" },
      },
      status,
      routineDefinitionFixture,
    );
    const projected = detail(call);
    assert.deepEqual(projected.outcome, { type: "UNSUCCEEDED", status });
    assert.equal(
      toolCallActionMessageKey("updateRoutine", status),
      status === "failed"
        ? "actionFailed.updateRoutine"
        : "actionCancelled.updateRoutine",
    );
    assert.notEqual(
      toolCallActionMessageKey("updateRoutine", status),
      "action.updateRoutine",
    );
  }
});

void test("partial preparing arguments stay a localized in-progress action without invented data", () => {
  const call = {
    ...routineCallFixture("create_routine", {}, "preparing", null),
    arguments: "{",
  };
  const projected = detail(call);
  assert.equal(projected.request, null);
  assert.deepEqual(projected.outcome, { type: "PENDING" });
  assert.equal(
    toolCallActionMessageKey("createRoutine", "preparing"),
    "actionRunning.createRoutine",
  );
});

void test("completed inspection distinguishes absent definitions rather than inventing one", () => {
  const call = routineCallFixture(
    "inspect_routine",
    { slug: "traffic", record_limit: 100 },
    "completed",
    { routine: null },
  );
  const projected = detail(call);
  assert.deepEqual(projected.outcome, {
    type: "COMPLETED",
    result: { type: "inspection", detail: null },
  });
  assert.equal(knownToolPresentation(call).type, "specialized");
});

void test("completion separates objective failure, result, hint, notification and failed delivery", () => {
  const work: RoutineWorkView = {
    ...routineWorkFixture,
    objective_outcome: "failed",
    notify: true,
    message: "The approved source could not be reached.",
  };
  const execution = {
    ...routineCompletionFixture,
    work,
    delivery_status: "failed",
    delivery_error: "Current Primary unavailable.",
  };
  const projected = detail(
    routineCallFixture(
      "record_routine_result",
      { slug: "traffic", execution_id: "occurrence-a", work },
      "completed",
      { created: true, execution },
    ),
  );
  assert.equal(projected.request?.type, "recordRoutineResult");
  assert.equal(projected.outcome.type, "COMPLETED");
  if (projected.outcome.result.type !== "completion") {
    throw new Error("Expected recorded completion");
  }
  assert.equal(
    projected.outcome.result.execution.work.objective_outcome,
    "failed",
  );
  assert.equal(projected.outcome.result.execution.work.notify, true);
  assert.equal(
    projected.outcome.result.execution.work.next_hint,
    work.next_hint,
  );
  assert.equal(projected.outcome.result.execution.delivery_status, "failed");
});

void test("duplicate completion preserves canonical work instead of displaying the new request as applied", () => {
  const input = {
    slug: "traffic",
    execution_id: "occurrence-a",
    work: {
      ...routineWorkFixture,
      result: "A changed request that must not replace saved work.",
    },
  };
  const projected = detail(
    routineCallFixture("record_routine_result", input, "completed", {
      created: false,
      execution: routineCompletionFixture,
    }),
  );
  assert.equal(projected.outcome.type, "COMPLETED");
  if (projected.outcome.result.type !== "completion") {
    throw new Error("Expected existing completion");
  }
  assert.equal(projected.outcome.result.created, false);
  assert.equal(
    projected.outcome.result.execution.work.result,
    routineWorkFixture.result,
  );
  assert.deepEqual(
    knownToolPresentation(
      routineCallFixture("record_routine_result", input, "completed", {
        created: true,
        execution: routineCompletionFixture,
      }),
    ),
    { type: "generic", reason: "invalid-output" },
  );
});

void test("untrusted source collisions and invalid cross-field outputs remain diagnostic fallbacks", () => {
  const call = routineCallFixture(
    "create_routine",
    routineDefinitionFixture.content,
    "completed",
    routineDefinitionFixture,
  );
  const sourceLess = { ...call };
  delete sourceLess.toolkitSource;
  for (const builtin of [sourceLess, { ...call, toolkitSource: null }]) {
    assert.equal(detail(builtin).outcome.type, "COMPLETED");
  }
  assert.deepEqual(
    knownToolPresentation({
      ...call,
      toolkitSource: {
        toolkit_config_id: "foreign",
        toolkit_slug: "routine",
        toolkit_type: "mcp",
        toolkit_name: "Foreign toolkit",
      },
    }),
    { type: "generic", reason: "unregistered" },
  );
  assert.deepEqual(
    knownToolPresentation({
      ...call,
      arguments: JSON.stringify({
        ...routineDefinitionFixture.content,
        session_id: "foreign",
      }),
    }),
    { type: "generic", reason: "invalid-arguments" },
  );
  assert.deepEqual(
    knownToolPresentation(
      routineCallFixture(
        "record_routine_result",
        {
          slug: "traffic",
          execution_id: "occurrence-a",
          work: {
            ...routineWorkFixture,
            message: "Silent work cannot contain this",
          },
        },
        "running",
        null,
      ),
    ),
    { type: "generic", reason: "invalid-arguments" },
  );
  assert.deepEqual(
    knownToolPresentation(
      routineCallFixture(
        "record_routine_result",
        {
          slug: "traffic",
          execution_id: "occurrence-a",
          work: routineWorkFixture,
        },
        "completed",
        {
          created: true,
          execution: {
            ...routineCompletionFixture,
            delivery_status: "delivered",
          },
        },
      ),
    ),
    { type: "generic", reason: "invalid-output" },
  );
});
