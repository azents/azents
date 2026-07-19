import assert from "node:assert/strict";
import test from "node:test";

import {
  projectSubscriptionUsageState,
  subscriptionUsageAdditionalLimits,
  subscriptionUsageProgressColor,
  subscriptionUsageSummaryLimits,
  supportsSubscriptionUsage,
} from "./subscriptionUsage.ts";
import type {
  SubscriptionUsageAvailableResponse,
  SubscriptionUsageExternalResponse,
} from "@azents/public-client";

const available: SubscriptionUsageAvailableResponse = {
  type: "available",
  integration_id: "integration-1",
  provider: "chatgpt_oauth",
  fetched_at: "2026-07-19T00:00:00Z",
  plan_label: "Pro",
  limits: [
    {
      id: "primary",
      label: "Primary",
      used_percent: 20,
      window_minutes: 300,
      resets_at: null,
      primary: true,
    },
    {
      id: "secondary",
      label: "Secondary",
      used_percent: 80,
      window_minutes: 10_080,
      resets_at: null,
      primary: true,
    },
    {
      id: "additional",
      label: "Additional",
      used_percent: 100,
      window_minutes: null,
      resets_at: null,
      primary: false,
    },
  ],
  financial_details: null,
};

void test("only subscription OAuth providers are eligible", () => {
  assert.equal(supportsSubscriptionUsage("chatgpt_oauth"), true);
  assert.equal(supportsSubscriptionUsage("xai_oauth"), true);
  assert.equal(supportsSubscriptionUsage("openai"), false);
  assert.equal(supportsSubscriptionUsage("xai"), false);
});

void test("unsupported and disabled integrations do not load usage", () => {
  const query = {
    data: null,
    isError: false,
    isFetching: false,
    isLoading: false,
    lastSuccessfulSnapshot: null,
  };
  assert.deepEqual(projectSubscriptionUsageState("openai", true, query), {
    type: "IDLE",
  });
  assert.deepEqual(
    projectSubscriptionUsageState("chatgpt_oauth", false, query),
    { type: "DISABLED" },
  );
});

void test("successful responses project to available and external states", () => {
  assert.deepEqual(
    projectSubscriptionUsageState("chatgpt_oauth", true, {
      data: available,
      isError: false,
      isFetching: false,
      isLoading: false,
      lastSuccessfulSnapshot: null,
    }),
    { type: "AVAILABLE", snapshot: available, refreshing: false },
  );

  const external: SubscriptionUsageExternalResponse = {
    type: "external",
    integration_id: "integration-2",
    provider: "xai_oauth",
    fetched_at: "2026-07-19T00:00:00Z",
    url: "https://grok.com/usage",
    message: "Usage is managed on xAI.",
  };
  assert.deepEqual(
    projectSubscriptionUsageState("xai_oauth", true, {
      data: external,
      isError: false,
      isFetching: true,
      isLoading: false,
      lastSuccessfulSnapshot: null,
    }),
    { type: "EXTERNAL", snapshot: external, refreshing: true },
  );
});

void test("available data remains visible after a refresh error", () => {
  const state = projectSubscriptionUsageState("chatgpt_oauth", true, {
    data: available,
    isError: true,
    isFetching: false,
    isLoading: false,
    lastSuccessfulSnapshot: null,
  });
  assert.deepEqual(state, {
    type: "STALE_ERROR",
    snapshot: available,
  });
});

void test("a typed unavailable refresh preserves the last successful snapshot", () => {
  const state = projectSubscriptionUsageState("chatgpt_oauth", true, {
    data: {
      type: "unavailable",
      integration_id: "integration-1",
      provider: "chatgpt_oauth",
      fetched_at: "2026-07-19T00:01:00Z",
      message: "Subscription usage is temporarily unavailable.",
      reason: "temporarily_unavailable",
      retryable: true,
    },
    isError: false,
    isFetching: false,
    isLoading: false,
    lastSuccessfulSnapshot: available,
  });
  assert.deepEqual(state, {
    type: "STALE_ERROR",
    snapshot: available,
  });
});

void test("an initial request failure is card-local unavailable state", () => {
  assert.deepEqual(
    projectSubscriptionUsageState("xai_oauth", true, {
      data: null,
      isError: true,
      isFetching: false,
      isLoading: false,
      lastSuccessfulSnapshot: null,
    }),
    { type: "UNAVAILABLE", reason: null, retryable: true },
  );
});

void test("summary shows two primary limits and discloses the rest", () => {
  assert.deepEqual(
    subscriptionUsageSummaryLimits(available).map((limit) => limit.id),
    ["primary", "secondary"],
  );
  assert.deepEqual(
    subscriptionUsageAdditionalLimits(available).map((limit) => limit.id),
    ["additional"],
  );
});

void test("progress colors follow normal, warning, and danger thresholds", () => {
  assert.equal(subscriptionUsageProgressColor(74.9), "blue");
  assert.equal(subscriptionUsageProgressColor(75), "yellow");
  assert.equal(subscriptionUsageProgressColor(94.9), "yellow");
  assert.equal(subscriptionUsageProgressColor(95), "red");
});
