import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SessionSystemPromptView } from "./SessionContextView";
import type {
  SessionContextResponse,
  SessionContextSystemPromptFragmentResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const developerPrompt: SessionContextSystemPromptFragmentResponse = {
  id: "developer-prompt-1",
  source: "developer_prompt",
  label: "Subagent collaboration guidance",
  content:
    "Delegate only when the user explicitly requests delegation. Keep the root agent responsible for synthesis.",
  preview:
    "Delegate only when the user explicitly requests delegation. Keep the root agent responsible for synthesis.",
  length: 106,
  metadata: {
    order: "1",
    toolkit: "subagent",
  },
};

const context: SessionContextResponse = {
  session: {
    id: "session-1",
    agent_id: "agent-1",
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  },
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
  system_prompt: {
    agent_prompt: null,
    toolkit_prompts: [],
    developer_prompts: [developerPrompt],
    injected_prompts: [],
    final_prompt: null,
  },
  raw_events: [],
};

const meta = {
  component: SessionSystemPromptView,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(960)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    context,
  },
} satisfies Meta<typeof SessionSystemPromptView>;

export default meta;

type Story = StoryObj<typeof meta>;

export const DeveloperPromptList = {} satisfies Story;

export const DeveloperPromptDetail = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "View details" }));
    await expect(
      canvas.getByText(
        "Delegate only when the user explicitly requests delegation. Keep the root agent responsible for synthesis.",
      ),
    ).toBeVisible();
  },
} satisfies Story;

export const NoDeveloperPrompts = {
  args: {
    context: {
      ...context,
      system_prompt: {
        agent_prompt: null,
        toolkit_prompts: [],
        developer_prompts: [],
        injected_prompts: [],
        final_prompt: null,
      },
    },
  },
} satisfies Story;
