import type {
  SubscriptionUsageAvailableResponse,
  SubscriptionUsageExternalResponse,
  SubscriptionUsageUnavailableReason,
  SubscriptionUsageUnavailableResponse,
} from "@azents/public-client";

export type SubscriptionUsageResponse =
  | SubscriptionUsageAvailableResponse
  | SubscriptionUsageExternalResponse
  | SubscriptionUsageUnavailableResponse;

export type SubscriptionUsageSnapshot =
  | SubscriptionUsageAvailableResponse
  | SubscriptionUsageExternalResponse;

export type SubscriptionUsageState =
  | { type: "IDLE" }
  | { type: "DISABLED" }
  | { type: "LOADING" }
  | {
      type: "AVAILABLE";
      snapshot: SubscriptionUsageAvailableResponse;
      refreshing: boolean;
    }
  | {
      type: "EXTERNAL";
      snapshot: SubscriptionUsageExternalResponse;
      refreshing: boolean;
    }
  | {
      type: "UNAVAILABLE";
      reason: SubscriptionUsageUnavailableReason | null;
      retryable: boolean;
    }
  | {
      type: "STALE_ERROR";
      snapshot: SubscriptionUsageSnapshot;
    };

export interface SubscriptionUsageQueryProjection {
  data: SubscriptionUsageResponse | null;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
}

export function supportsSubscriptionUsage(provider: string): boolean {
  return provider === "chatgpt_oauth" || provider === "xai_oauth";
}

export function projectSubscriptionUsageState(
  provider: string,
  enabled: boolean,
  query: SubscriptionUsageQueryProjection,
): SubscriptionUsageState {
  if (!supportsSubscriptionUsage(provider)) {
    return { type: "IDLE" };
  }
  if (!enabled) {
    return { type: "DISABLED" };
  }

  const { data } = query;
  if (data?.type === "available") {
    if (query.isError) {
      return { type: "STALE_ERROR", snapshot: data };
    }
    return {
      type: "AVAILABLE",
      snapshot: data,
      refreshing: query.isFetching,
    };
  }
  if (data?.type === "external") {
    if (query.isError) {
      return { type: "STALE_ERROR", snapshot: data };
    }
    return {
      type: "EXTERNAL",
      snapshot: data,
      refreshing: query.isFetching,
    };
  }
  if (data?.type === "unavailable") {
    return {
      type: "UNAVAILABLE",
      reason: data.reason,
      retryable: data.retryable,
    };
  }
  if (query.isLoading || query.isFetching) {
    return { type: "LOADING" };
  }
  if (query.isError) {
    return { type: "UNAVAILABLE", reason: null, retryable: true };
  }
  return { type: "LOADING" };
}

export function subscriptionUsageProgressColor(
  usedPercent: number,
): "blue" | "yellow" | "red" {
  if (usedPercent >= 95) {
    return "red";
  }
  if (usedPercent >= 75) {
    return "yellow";
  }
  return "blue";
}

export function subscriptionUsageSummaryLimits(
  snapshot: SubscriptionUsageAvailableResponse,
): SubscriptionUsageAvailableResponse["limits"] {
  const primary = snapshot.limits.filter((limit) => limit.primary);
  const fallback = snapshot.limits.filter((limit) => !limit.primary);
  return [...primary, ...fallback].slice(0, 2);
}

export function subscriptionUsageAdditionalLimits(
  snapshot: SubscriptionUsageAvailableResponse,
): SubscriptionUsageAvailableResponse["limits"] {
  const summaryIds = new Set(
    subscriptionUsageSummaryLimits(snapshot).map((limit) => limit.id),
  );
  return snapshot.limits.filter((limit) => !summaryIds.has(limit.id));
}
