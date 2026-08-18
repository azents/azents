import assert from "node:assert/strict";
import test from "node:test";
import {
  getArray,
  getOptionalString,
  getString,
  getStringArray,
  isOneOf,
  isRecord,
  isString,
  isStringArray,
  parseJsonRecord,
} from "./unknown-value.ts";

await test("narrows records without accepting arrays or null", () => {
  assert.equal(isRecord({ key: "value" }), true);
  assert.equal(isRecord([]), false);
  assert.equal(isRecord(null), false);
});

await test("reads only valid string values", () => {
  assert.equal(getString("value"), "value");
  assert.equal(getString(42, "fallback"), "fallback");
  assert.equal(getOptionalString("value"), "value");
  assert.equal(getOptionalString(false), null);
  assert.deepEqual(getStringArray(["one", 2, "three"]), ["one", "three"]);
  assert.equal(isStringArray(["one", "two"]), true);
  assert.equal(isStringArray([]), true);
  assert.equal(isStringArray(["one", 2]), false);
});

await test("filters generic arrays through the supplied predicate", () => {
  assert.deepEqual(getArray(["one", 2, "three"], isString), ["one", "three"]);
  assert.deepEqual(getArray("not-an-array", isString), []);
});

await test("narrows literal values by membership", () => {
  const candidates = ["one", "two"] as const;
  assert.equal(isOneOf("two", candidates), true);
  assert.equal(isOneOf("three", candidates), false);
  assert.equal(isOneOf(2, candidates), false);
});

await test("parses only JSON objects", () => {
  assert.deepEqual(parseJsonRecord('{"key":"value"}'), { key: "value" });
  assert.equal(parseJsonRecord('["value"]'), null);
  assert.equal(parseJsonRecord("not-json"), null);
});
