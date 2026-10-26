import assert from "node:assert/strict";
import test from "node:test";
import {
  boundRunActivitySource,
  latestRunActivitySource,
} from "./activityRunPresentation.ts";
import type { ToolActivityPresentationItem } from "@azents/session-core/toolActivityPresentation";
import type { ChatMessage } from "@azents/session-core/types";

function message(id: string, role: ChatMessage["role"]): ChatMessage {
  return { id, role, content: null, createdAt: "2026-10-26T00:00:00Z" };
}
function activity(id: string, index: number): ToolActivityPresentationItem {
  return {
    id,
    type: "activity",
    activity: {
      id,
      firstMessageId: id,
      startedAt: null,
      startMessageIndex: index,
      endMessageIndex: index,
      events: [],
      usage: null,
    },
  };
}

void test("selects current activity after the latest Run completion boundary without a new human input", () => {
  const previous = activity("previous", 1);
  const current = activity("current", 3);
  const messages = [
    message("input", "user"),
    message("old-tool", "tool"),
    message("end", "run_complete"),
    message("new-tool", "tool"),
  ];
  assert.equal(latestRunActivitySource([previous, current], messages), current);
  assert.equal(latestRunActivitySource([previous], messages.slice(0, 3)), null);
});

void test("a new human input separates historical activity from the active Run", () => {
  const previous = activity("previous", 0);
  assert.equal(
    latestRunActivitySource(
      [previous],
      [message("old", "tool"), message("input", "user")],
    ),
    null,
  );
});

void test("detached history retains only its known current Run Activity binding", () => {
  const previous = activity("previous", 0);
  const current = activity("current", 1);
  const binding = { runId: "run-1", activityId: current.id };
  assert.equal(
    boundRunActivitySource([previous, current], binding, "run-1"),
    current,
  );
  assert.equal(
    boundRunActivitySource([previous, current], binding, "run-2"),
    null,
  );
  assert.equal(
    boundRunActivitySource([previous, current], binding, null),
    null,
  );
  assert.equal(boundRunActivitySource([previous], binding, "run-1"), null);
  assert.equal(boundRunActivitySource([previous], null, "run-1"), null);
});
