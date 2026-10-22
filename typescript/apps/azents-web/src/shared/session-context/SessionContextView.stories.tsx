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
