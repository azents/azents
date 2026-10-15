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
void test("stale or incomplete links never switch silently to another page", () => {
  assert.deepEqual(browserProjectionState([page], { type: "NONE" }, true), {
    type: "SELECT_PAGE",
    pages: [page],
  });
  assert.deepEqual(browserProjectionState([page], { type: "INVALID" }, true), {
    type: "CLOSED_TARGET",
    pages: [page],
  });
  assert.deepEqual(
    browserProjectionState(
      [page],
      { type: "TARGET", target: { ...target, resource_incarnation: "old" } },
      true,
    ),
    { type: "CLOSED_TARGET", pages: [page] },
  );
});
void test("REST selection awaits actual admitted viewer status before enabling input", () => {
  const state = browserProjectionState(
    [page],
    { type: "TARGET", target },
    true,
  );
  assert.equal(state.type, "READY");
  assert.equal(state.connection, "connecting");
  assert.equal(state.canInput, false);
  assert.equal(state.canClose, true);
  assert.equal(state.image, null);
});
