import assert from "node:assert/strict";
import test from "node:test";
import { historicalMemoryExecutionInputSchema } from "./historical-memory-execution-input.ts";

await test("versioned execution updates accept an explicit unlimited limit", () => {
  assert.deepEqual(
    historicalMemoryExecutionInputSchema.parse({
      expectedVersion: 3,
      maxTurns: null,
      timeoutSeconds: 600,
    }),
    { expectedVersion: 3, maxTurns: null, timeoutSeconds: 600 },
  );
});

await test("execution updates require version and positive integer cutoffs", () => {
  const valid = { expectedVersion: 3, maxTurns: 12, timeoutSeconds: 600 };
  for (const input of [
    { ...valid, expectedVersion: -1 },
    { ...valid, expectedVersion: 0.5 },
    { ...valid, maxTurns: 0 },
    { ...valid, maxTurns: 1.5 },
    { ...valid, timeoutSeconds: 0 },
    { ...valid, timeoutSeconds: -1 },
    { ...valid, timeoutSeconds: 0.5 },
    { ...valid, timeoutSeconds: null },
    { maxTurns: null, timeoutSeconds: 600 },
    { expectedVersion: 3, timeoutSeconds: 600 },
  ]) {
    assert.equal(
      historicalMemoryExecutionInputSchema.safeParse(input).success,
      false,
    );
  }
});
