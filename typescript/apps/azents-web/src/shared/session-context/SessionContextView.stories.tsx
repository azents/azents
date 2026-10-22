import { expect, waitFor } from "storybook/test";
import { expectReadableContrast } from "@/shared/storybook/contrast";
import { SessionContextPresentation } from "./SessionContextView";
import type { SessionContextResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const context: SessionContextResponse = {
  session: { id: "session-preview", agent_id: "agent-preview" },
  usage: null,
  stats: {
    total_events: 0,
    user_messages: 0,
    assistant_messages: 0,
    reasoning_events: 0,
    tool_calls: 0,
    tool_results: 0,
    turn_markers: 0,
    total_cost_usd: null,
  },
  breakdown: [],
  raw_events: [],
};
const meta = {
  component: SessionContextPresentation,
  tags: ["ci-contract"],
  args: {
    context,
    systemPromptHref: "#system-prompt",
    rawEventsHref: "#raw-events",
    usage: {
      totalTokens: null,
      promptTokens: null,
      completionTokens: null,
      reasoningTokens: null,
      cachedTokens: null,
      cacheCreationTokens: null,
    },
  },
} satisfies Meta<typeof SessionContextPresentation>;
export default meta;
type Story = StoryObj<typeof meta>;
export const UnavailableCounters = {} satisfies Story;
export const BreakdownLight: Story = {
  globals: { colorScheme: "light" },
  args: {
    context: {
      ...context,
      breakdown: [
        { key: "system", tokens: 20, percent: 20 },
        { key: "user", tokens: 20, percent: 20 },
        { key: "assistant", tokens: 20, percent: 20 },
        { key: "tool", tokens: 20, percent: 20 },
        { key: "other", tokens: 20, percent: 20 },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    await waitFor(async () => {
      const badges = canvasElement.querySelectorAll(
        '.mantine-Badge-root[data-variant="filled"]',
      );
      await expect(badges).toHaveLength(5);
      for (const badge of badges) {
        await expectReadableContrast(badge);
      }
    });
  },
};
export const BreakdownDark: Story = {
  ...BreakdownLight,
  globals: { colorScheme: "dark" },
};
export const UsageCounters = {
  args: {
    usage: {
      totalTokens: 100,
      promptTokens: 60,
      completionTokens: 40,
      reasoningTokens: 20,
      cachedTokens: 10,
      cacheCreationTokens: 0,
    },
  },
} satisfies Story;
