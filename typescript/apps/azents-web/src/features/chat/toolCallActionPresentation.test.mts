import assert from "node:assert/strict";
import test from "node:test";
import { toolCallActionMessageKey } from "./toolCallActionPresentation.ts";

void test("uses in-progress action messages for preparing and running tools", () => {
  assert.equal(
    toolCallActionMessageKey("command", "preparing"),
    "actionRunning.command",
  );
  assert.equal(
    toolCallActionMessageKey("command", "running"),
    "actionRunning.command",
  );
});

void test("uses completed action messages for terminal tool states", () => {
  assert.equal(toolCallActionMessageKey("edit", "completed"), "action.edit");
  assert.equal(toolCallActionMessageKey("edit", "failed"), "action.edit");
  assert.equal(toolCallActionMessageKey("edit", "cancelled"), "action.edit");
  assert.equal(toolCallActionMessageKey("edit", "interrupted"), "action.edit");
});
