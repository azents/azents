import assert from "node:assert/strict";
import test from "node:test";
import { getServiceAccountKey } from "./service-account-fields.ts";
void test("provider key decoder preserves valid fields without coercing or accepting absent email", () => {
  const key = { client_email: "fixture@example.com", fixture: "synthetic" };
  assert.equal(getServiceAccountKey(key), key);
  for (const invalid of [
    null,
    [],
    "",
    {},
    { client_email: "" },
    { client_email: 1 },
  ]) {
    assert.equal(getServiceAccountKey(invalid), null);
  }
});
