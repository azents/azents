import assert from "node:assert/strict";
import test from "node:test";
import {
  knownReasoningEffort,
  REASONING_EFFORT_ORDER,
  reasoningEffortInputSchema,
  reasoningEffortLevels,
} from "./reasoning-effort.ts";
import type { ModelCapabilities } from "@azents/public-client";

const DOMAIN_EFFORTS = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

/** Published Astra and Sol configuration after raw ultra is skipped, not aliased. */
const ASTRA_SOL_CANONICAL_EFFORTS = [
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

const RAW_OBSERVED_SOL_EFFORTS = [
  ...ASTRA_SOL_CANONICAL_EFFORTS,
  "ultra",
] as const;

void test("reasoning effort domain remains the original seven levels", () => {
  assert.deepEqual([...REASONING_EFFORT_ORDER], [...DOMAIN_EFFORTS]);
  assert.equal(REASONING_EFFORT_ORDER.length, 7);
  for (const effort of DOMAIN_EFFORTS) {
    assert.equal(knownReasoningEffort(effort), effort);
    assert.equal(reasoningEffortInputSchema.parse(effort), effort);
  }
});

void test("serialized validated effort input rejects raw ultra", () => {
  const nullableEffort = reasoningEffortInputSchema.nullable().optional();
  const accepted: unknown = JSON.parse(
    JSON.stringify({ reasoning_effort: "max" }),
  );
  const rejected: unknown = JSON.parse(
    JSON.stringify({ reasoning_effort: "ultra" }),
  );
  assert.equal(isEffortRecord(accepted), true);
  assert.equal(isEffortRecord(rejected), true);
  if (!isEffortRecord(accepted) || !isEffortRecord(rejected)) {
    return;
  }
  assert.equal(nullableEffort.parse(accepted.reasoning_effort), "max");
  assert.equal(
    nullableEffort.safeParse(rejected.reasoning_effort).success,
    false,
  );
});

function isEffortRecord(
  value: unknown,
): value is { reasoning_effort: unknown } {
  return (
    typeof value === "object" && value !== null && "reasoning_effort" in value
  );
}

void test("raw observed Sol ultra is not configurable or selected", () => {
  const configurable = RAW_OBSERVED_SOL_EFFORTS.flatMap((effort) => {
    const selected = knownReasoningEffort(effort);
    return selected == null ? [] : [selected];
  });
  assert.equal(RAW_OBSERVED_SOL_EFFORTS.length, 6);
  assert.deepEqual(configurable, [...ASTRA_SOL_CANONICAL_EFFORTS]);
  assert.equal(configurable.length, 5);
  assert.equal(knownReasoningEffort("ultra"), null);
  assert.equal(reasoningEffortInputSchema.safeParse("ultra").success, false);
  assert.equal(knownReasoningEffort("max"), "max");

  const published: ModelCapabilities = {
    reasoning: {
      supported: true,
      effort_levels: [...ASTRA_SOL_CANONICAL_EFFORTS],
    },
  };
  assert.deepEqual(reasoningEffortLevels(published), [
    ...ASTRA_SOL_CANONICAL_EFFORTS,
  ]);
});
