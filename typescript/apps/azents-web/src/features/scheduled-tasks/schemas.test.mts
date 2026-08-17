import assert from "node:assert/strict";
import test from "node:test";
import { parseScheduledTaskDraft, toLocalDateTimeInput } from "./schemas.ts";

void test("normalizes one-time local input to an RFC 3339 instant", () => {
  const result = parseScheduledTaskDraft({
    sessionId: "session_01",
    title: "  Publish release notes  ",
    objective: "  Summarize the completed release.  ",
    scheduleType: "once",
    at: "2026-08-20T09:30",
    cron: "",
    timezone: "UTC",
    channelId: null,
  });
  assert.equal(result.success, true);
  assert.equal(result.values.title, "Publish release notes");
  assert.equal(result.values.objective, "Summarize the completed release.");
  assert.match(result.values.at ?? "", /2026-08-20T/);
  assert.equal(result.values.cron, null);
  assert.equal(result.values.timezone, null);
});

void test("normalizes recurring input without a one-time instant", () => {
  const result = parseScheduledTaskDraft({
    sessionId: "session_01",
    title: "Daily status",
    objective: "Post the daily status summary.",
    scheduleType: "cron",
    at: "",
    cron: " 0 9 * * 1-5 ",
    timezone: " Asia/Seoul ",
    channelId: "binding_01",
  });
  assert.deepEqual(result, {
    success: true,
    values: {
      sessionId: "session_01",
      title: "Daily status",
      objective: "Post the daily status summary.",
      at: null,
      cron: "0 9 * * 1-5",
      timezone: "Asia/Seoul",
      channelId: "binding_01",
    },
  });
});

void test("returns stable localized form error keys", () => {
  const result = parseScheduledTaskDraft({
    sessionId: "",
    title: "",
    objective: "",
    scheduleType: "once",
    at: "",
    cron: "",
    timezone: "",
    channelId: null,
  });
  assert.deepEqual(result, { success: false, error: "sessionRequired" });
});

void test("projects a canonical instant into a datetime-local value", () => {
  assert.match(
    toLocalDateTimeInput("2026-08-20T09:30:00Z"),
    /^2026-08-(19|20)T/,
  );
  assert.equal(toLocalDateTimeInput("not-a-date"), "");
});
