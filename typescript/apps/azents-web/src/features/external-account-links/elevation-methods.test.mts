import assert from "node:assert/strict";
import test from "node:test";
import { elevationMethodsOrEmpty } from "./elevation-methods.ts";

void test("keeps a stable empty methods reference while the query has no response", () => {
  const first = elevationMethodsOrEmpty();
  const second = elevationMethodsOrEmpty();
  const loading = elevationMethodsOrEmpty(null);

  assert.strictEqual(first, second);
  assert.strictEqual(first, loading);
  assert.deepEqual(first, []);
});
