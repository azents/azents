import assert from "node:assert/strict";
import test from "node:test";
import { buildRuntimeMetricSparklineSegments } from "./presentation.ts";
import type { AgentRuntimeSystemMetricsSampleResponse } from "@azents/public-client";

function sample(
  measuredAt: string,
  cpu: AgentRuntimeSystemMetricsSampleResponse["cpu"],
): AgentRuntimeSystemMetricsSampleResponse {
  return {
    measured_at: measuredAt,
    scope: "container",
    cpu,
    memory: { availability: "unavailable", used: null, total: null },
    disk: { availability: "unavailable", used: null, total: null },
  };
}

void test("preserves unavailable observations and missing intervals as trend gaps", () => {
  const segments = buildRuntimeMetricSparklineSegments(
    [
      sample("2026-08-24T09:00:00Z", {
        availability: "available",
        used: 200,
        total: 1_000,
      }),
      sample("2026-08-24T09:01:00Z", {
        availability: "available",
        used: 400,
        total: 1_000,
      }),
      sample("2026-08-24T09:02:00Z", {
        availability: "unavailable",
        used: null,
        total: null,
      }),
      sample("2026-08-24T09:05:00Z", {
        availability: "available",
        used: 600,
        total: 1_000,
      }),
      sample("2026-08-24T09:06:00Z", {
        availability: "available",
        used: 800,
        total: 1_000,
      }),
    ],
    "cpu",
    120,
    28,
  );

  assert.equal(segments.length, 2);
  assert.equal(segments[0]?.length, 2);
  assert.equal(segments[1]?.length, 2);
  assert.equal(segments[0][0]?.x, 0);
  assert.equal(segments[1][1]?.x, 120);
});

void test("does not create trend points for an unsupported series", () => {
  assert.deepEqual(
    buildRuntimeMetricSparklineSegments(
      [
        sample("2026-08-24T09:00:00Z", {
          availability: "unsupported",
          used: null,
          total: null,
        }),
      ],
      "cpu",
      120,
      28,
    ),
    [],
  );
});
