import assert from "node:assert/strict";
import test from "node:test";
import { humanSenderPresentation } from "./senderPresentation.ts";

void test("uses the current Workspace profile only for its matching stored sender", () => {
  assert.deepEqual(
    humanSenderPresentation("user-1", {
      userId: "user-1",
      name: "Ada Lovelace",
    }),
    { type: "AVAILABLE", name: "Ada Lovelace" },
  );
});

void test("does not infer a sender for historical or different-user provenance", () => {
  assert.deepEqual(humanSenderPresentation(null, null), {
    type: "UNAVAILABLE",
  });
  assert.deepEqual(
    humanSenderPresentation("user-2", {
      userId: "user-1",
      name: "Ada Lovelace",
    }),
    { type: "UNAVAILABLE" },
  );
});
