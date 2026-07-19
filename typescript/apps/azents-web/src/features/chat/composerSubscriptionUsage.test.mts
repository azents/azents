import assert from "node:assert/strict";
import test from "node:test";

import {
  composerSubscriptionSeverity,
  projectComposerSubscriptionIndicator,
  resolveComposerSubscriptionSelection,
} from "./composerSubscriptionUsage.ts";
import type {
  AgentResponse,
  SubscriptionUsageAvailableResponse,
} from "@azents/public-client";

const modelSelection = {
  llm_provider_integration_id: "integration-chatgpt",
  provider: "chatgpt_oauth" as const,
  model_identifier: "gpt-5",
  model_display_name: "GPT-5",
  model_developer: "openai" as const,
  model_family: "gpt-5",
  normalized_capabilities: {
    reasoning: { supported: false, effort_levels: [] },
    built_in_tools: { supported: [] },
    context_window: { max_input_tokens: 128_000, max_output_tokens: null },
    modalities: { input: ["text" as const], output: ["text" as const] },
    tool_calling: { supported: true },
    parameters: {},
    compatibility: {},
  },
  model_snapshot: {},
  source_metadata: null,
  last_refreshed_at: null,
};

const options: AgentResponse["selectable_model_options"] = [
  {
    label: "Default",
    model_selection: modelSelection,
    settings: {
      context_window_tokens: null,
      max_output_tokens: null,
      builtin_tools: [],
      subagent_enabled: true,
      subagent_guidance: null,
    },
  },
];

const available: SubscriptionUsageAvailableResponse = {
  type: "available",
  integration_id: "integration-chatgpt",
  provider: "chatgpt_oauth",
  fetched_at: "2026-07-19T00:00:00Z",
  plan_label: "Plus",
  limits: [
    {
      id: "primary",
      label: "5 hour limit",
      used_percent: 73.4,
      window_minutes: 300,
      resets_at: "2026-07-19T02:00:00Z",
      primary: true,
    },
  ],
  financial_details: {
    type: "chatgpt",
    has_credits: true,
    unlimited: false,
    balance: "sensitive",
    spend_limit: null,
    spend_used: null,
    spend_remaining_percent: null,
    spend_resets_at: null,
    reached_type: null,
  },
};

void test("selected model resolves and switches its provider integration", () => {
  const switchableOptions: AgentResponse["selectable_model_options"] = [
    ...options,
    {
      label: "Fast",
      model_selection: {
        ...modelSelection,
        llm_provider_integration_id: "integration-xai",
        provider: "xai_oauth",
      },
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
        subagent_enabled: true,
        subagent_guidance: null,
      },
    },
    {
      label: "OpenRouter",
      model_selection: {
        ...modelSelection,
        llm_provider_integration_id: "integration-openrouter",
        provider: "openrouter",
      },
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
        subagent_enabled: true,
        subagent_guidance: null,
      },
    },
    {
      label: "Kimi",
      model_selection: {
        ...modelSelection,
        llm_provider_integration_id: "integration-kimi",
        provider: "kimi_oauth",
      },
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
        subagent_enabled: true,
        subagent_guidance: null,
      },
    },
  ];

  assert.deepEqual(
    resolveComposerSubscriptionSelection(switchableOptions, "Default"),
    {
      integrationId: "integration-chatgpt",
      provider: "chatgpt_oauth",
    },
  );
  assert.deepEqual(
    resolveComposerSubscriptionSelection(switchableOptions, "Fast"),
    {
      integrationId: "integration-xai",
      provider: "xai_oauth",
    },
  );
  assert.deepEqual(
    resolveComposerSubscriptionSelection(switchableOptions, "OpenRouter"),
    {
      integrationId: "integration-openrouter",
      provider: "openrouter",
    },
  );
  assert.deepEqual(
    resolveComposerSubscriptionSelection(switchableOptions, "Kimi"),
    {
      integrationId: "integration-kimi",
      provider: "kimi_oauth",
    },
  );
  assert.equal(
    resolveComposerSubscriptionSelection(switchableOptions, "Missing"),
    null,
  );
  assert.equal(
    resolveComposerSubscriptionSelection(
      [
        {
          label: "API key",
          model_selection: {
            ...modelSelection,
            llm_provider_integration_id: "integration-openai",
            provider: "openai",
          },
          settings: {
            context_window_tokens: null,
            max_output_tokens: null,
            builtin_tools: [],
            subagent_enabled: true,
            subagent_guidance: null,
          },
        },
      ],
      "API key",
    ),
    null,
  );
});

void test("composer severity uses session guidance thresholds", () => {
  assert.equal(composerSubscriptionSeverity(69.9), "normal");
  assert.equal(composerSubscriptionSeverity(70), "warning");
  assert.equal(composerSubscriptionSeverity(89.9), "warning");
  assert.equal(composerSubscriptionSeverity(90), "critical");
});

void test("available and stale snapshots project the primary limit", () => {
  assert.deepEqual(
    projectComposerSubscriptionIndicator({
      type: "AVAILABLE",
      snapshot: available,
      refreshing: false,
    }),
    {
      type: "PERCENT",
      label: "5 hour limit",
      percent: 73.4,
      severity: "warning",
      stale: false,
    },
  );
  assert.deepEqual(
    projectComposerSubscriptionIndicator({
      type: "STALE_ERROR",
      snapshot: available,
    }),
    {
      type: "PERCENT",
      label: "5 hour limit",
      percent: 73.4,
      severity: "warning",
      stale: true,
    },
  );
});

void test("non-percent states stay explicit", () => {
  assert.deepEqual(projectComposerSubscriptionIndicator({ type: "IDLE" }), {
    type: "HIDDEN",
  });
  assert.deepEqual(projectComposerSubscriptionIndicator({ type: "LOADING" }), {
    type: "LOADING",
  });
  assert.deepEqual(
    projectComposerSubscriptionIndicator({
      type: "UNAVAILABLE",
      reason: "temporarily_unavailable",
      retryable: true,
    }),
    { type: "UNAVAILABLE" },
  );
});
