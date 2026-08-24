import type {
  AgentRuntimeSystemMetricObservationResponse,
  AgentRuntimeSystemMetricsSampleResponse,
} from "@azents/public-client";

export type RuntimeSystemMetricKey = "cpu" | "memory" | "disk";

export interface RuntimeMetricChartDatum {
  measuredAt: number;
  value: number | null;
}

const GAP_THRESHOLD_MS = 90_000;

function observationForMetric(
  sample: AgentRuntimeSystemMetricsSampleResponse,
  metric: RuntimeSystemMetricKey,
): AgentRuntimeSystemMetricObservationResponse {
  switch (metric) {
    case "cpu":
      return sample.cpu;
    case "memory":
      return sample.memory;
    case "disk":
      return sample.disk;
  }
}

function observationValue(
  observation: AgentRuntimeSystemMetricObservationResponse,
): number | null {
  if (observation.availability !== "available" || observation.used === null) {
    return null;
  }
  if (observation.total !== null) {
    return Math.min(
      Math.max((observation.used / observation.total) * 100, 0),
      100,
    );
  }
  return observation.used;
}

export function buildRuntimeMetricChartData(
  samples: AgentRuntimeSystemMetricsSampleResponse[],
  metric: RuntimeSystemMetricKey,
): RuntimeMetricChartDatum[] {
  if (samples.length === 0) {
    return [];
  }

  const data: RuntimeMetricChartDatum[] = [];
  let previousMeasuredAt: number | null = null;
  let previousValue: number | null = null;

  for (const sample of samples) {
    const measuredAt = Date.parse(sample.measured_at);
    if (!Number.isFinite(measuredAt)) {
      continue;
    }
    const value = observationValue(observationForMetric(sample, metric));
    if (
      previousMeasuredAt !== null &&
      previousValue !== null &&
      value !== null &&
      measuredAt - previousMeasuredAt > GAP_THRESHOLD_MS
    ) {
      data.push({
        measuredAt: previousMeasuredAt + (measuredAt - previousMeasuredAt) / 2,
        value: null,
      });
    }
    data.push({ measuredAt, value });
    previousMeasuredAt = measuredAt;
    previousValue = value;
  }

  return data.some((datum) => datum.value !== null) ? data : [];
}
