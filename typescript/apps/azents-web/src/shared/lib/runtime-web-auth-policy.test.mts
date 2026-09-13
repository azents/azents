import assert from "node:assert/strict";
import test from "node:test";
import {
  decodeMainBinding,
  encodeMainBinding,
} from "./runtime-web-auth-policy.ts";

void test("encodes and validates the host-only Main binding cookie", () => {
  const initiationId = "initiation0000000000000000000000";
  const secret = "secret000000000000000000000000000000";
  const encoded = encodeMainBinding(initiationId, secret);
  assert.deepEqual(decodeMainBinding(encoded), { initiationId, secret });
  assert.equal(decodeMainBinding(`short.${secret}`), null);
  assert.equal(decodeMainBinding(`${initiationId}.short`), null);
});
