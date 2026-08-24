import assert from "node:assert/strict";
import test from "node:test";
import { composeMessages } from "./message-composition.ts";

await test("composes namespace-scoped messages into the next-intl shape", () => {
  const messages = composeMessages([
    ["common", { save: "Save" }],
    ["workspace", { title: "Workspace" }],
  ]);

  assert.deepEqual(messages, {
    common: { save: "Save" },
    workspace: { title: "Workspace" },
  });
});

await test("rejects duplicate message namespaces", () => {
  assert.throws(
    () =>
      composeMessages([
        ["common", { save: "Save" }],
        ["common", { cancel: "Cancel" }],
      ]),
    /Duplicate message namespace: common/,
  );
});
