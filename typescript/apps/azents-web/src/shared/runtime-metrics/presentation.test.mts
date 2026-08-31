import assert from "node:assert/strict";
import test from "node:test";
import { buildRuntimeMetricChartData } from "./presentation.ts";
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
  const data = buildRuntimeMetricChartData(
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
  );

  assert.equal(data.length, 5);
  assert.deepEqual(
    data.map((datum) => datum.value),
    [20, 40, null, 60, 80],
  );
  assert.equal(data[0]?.measuredAt, Date.parse("2026-08-24T09:00:00Z"));
  assert.equal(data[4]?.measuredAt, Date.parse("2026-08-24T09:06:00Z"));
});

void test("inserts a null point when available samples have a delayed interval", () => {
  const data = buildRuntimeMetricChartData(
    [
      sample("2026-08-24T09:00:00Z", {
        availability: "available",
        used: 200,
        total: 1_000,
      }),
      sample("2026-08-24T09:05:00Z", {
        availability: "available",
        used: 800,
        total: 1_000,
      }),
    ],
    "cpu",
  );

  assert.deepEqual(
    data.map((datum) => datum.value),
    [20, null, 80],
  );
  assert.equal(data[1]?.measuredAt, Date.parse("2026-08-24T09:02:30Z"));
});

void test("does not create trend points for an unsupported series", () => {
  assert.deepEqual(
    buildRuntimeMetricChartData(
      [
        sample("2026-08-24T09:00:00Z", {
          availability: "unsupported",
          used: null,
          total: null,
        }),
      ],
      "cpu",
    ),
    [],
  );
});
