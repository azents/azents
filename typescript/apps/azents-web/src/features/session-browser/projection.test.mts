import assert from "node:assert/strict";
import test from "node:test";
import { browserProjectionState } from "./projection.ts";

const target = {
  task_id: "task",
  page_id: "page",
  resource_incarnation: "current",
};
const page = {
  target,
  taskLabel: "Task",
  title: "Page",
  url: "https://example.test",
};
const other = { ...page, target: { ...target, page_id: "other" } };

void test("missing, incomplete and closed links select the recent live Agent tab", () => {
  for (const linked of [
    { type: "NONE" },
    { type: "INVALID" },
    { type: "TARGET", target: { ...target, resource_incarnation: "old" } },
  ] as const) {
    const state = browserProjectionState([page, other], linked, true, [
      other.target,
    ]);
    assert.equal(state.type, "READY");
    assert.deepEqual(state.selected.target, other.target);
  }
});
void test("unknown or closed recent tabs fall back to the first live tab", () => {
  const state = browserProjectionState([page, other], { type: "NONE" }, true, [
    { ...target, page_id: "closed" },
  ]);
  assert.equal(state.type, "READY");
  assert.deepEqual(state.selected.target, target);
});
void test("explicit live tab selection is retained over Agent preference", () => {
  const state = browserProjectionState(
    [page, other],
    { type: "TARGET", target },
    true,
    [other.target],
  );
  assert.equal(state.type, "READY");
  assert.deepEqual(state.selected.target, target);
});
void test("empty tab lists guide creation regardless of an obsolete link", () => {
  assert.deepEqual(
    browserProjectionState([], { type: "TARGET", target }, true),
    { type: "EMPTY" },
  );
});
void test("automatic selection awaits actual admitted viewer status before enabling input", () => {
  const state = browserProjectionState([page], { type: "NONE" }, true);
  assert.equal(state.type, "READY");
  assert.equal(state.connection, "connecting");
  assert.equal(state.canInput, false);
  assert.equal(state.canClose, true);
  assert.equal(state.image, null);
});
