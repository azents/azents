import type {
  AgentRuntimeSystemMetricObservationResponse,
  AgentRuntimeSystemMetricsSampleResponse,
} from "@azents/public-client";

export type RuntimeSystemMetricKey = "cpu" | "memory" | "disk";

export interface RuntimeMetricSparklinePoint {
  x: number;
  y: number;
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

export function buildRuntimeMetricSparklineSegments(
  samples: AgentRuntimeSystemMetricsSampleResponse[],
  metric: RuntimeSystemMetricKey,
  width: number,
  height: number,
): RuntimeMetricSparklinePoint[][] {
  if (samples.length === 0) {
    return [];
  }

  const measuredSamples = samples
    .map((sample) => ({
      measuredAt: Date.parse(sample.measured_at),
      value: observationValue(observationForMetric(sample, metric)),
    }))
    .filter((sample) => Number.isFinite(sample.measuredAt));
  if (measuredSamples.length === 0) {
    return [];
  }

  const availableValues = measuredSamples.flatMap((sample) =>
    sample.value === null ? [] : [sample.value],
  );
  if (availableValues.length === 0) {
    return [];
  }

  const firstMeasuredAt = measuredSamples[0]?.measuredAt ?? 0;
  const lastMeasuredAt =
    measuredSamples[measuredSamples.length - 1]?.measuredAt ?? firstMeasuredAt;
  const timeRange = Math.max(lastMeasuredAt - firstMeasuredAt, 1);
  const minimumValue = Math.min(...availableValues);
  const maximumValue = Math.max(...availableValues);
  const valueRange = Math.max(maximumValue - minimumValue, 1);
  const segments: RuntimeMetricSparklinePoint[][] = [];
  let segment: RuntimeMetricSparklinePoint[] = [];
  let previousMeasuredAt: number | null = null;

  for (const sample of measuredSamples) {
    if (
      sample.value === null ||
      (previousMeasuredAt !== null &&
        sample.measuredAt - previousMeasuredAt > GAP_THRESHOLD_MS)
    ) {
      if (segment.length > 0) {
        segments.push(segment);
      }
      segment = [];
    }
    if (sample.value !== null) {
      segment.push({
        x: ((sample.measuredAt - firstMeasuredAt) / timeRange) * width,
        y: height - ((sample.value - minimumValue) / valueRange) * height,
      });
    }
    previousMeasuredAt = sample.measuredAt;
  }
  if (segment.length > 0) {
    segments.push(segment);
  }
  return segments;
}
