import { Box, Text } from "@mantine/core";
import { expect, within } from "storybook/test";
import { AgentSettingsLayout } from "./AgentSettingsLayout";
import type { AgentResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  id: "assistant",
  name: "Research assistant",
  description: "Research and writing for personal and Team Sessions.",
  type: "public",
  enabled: true,
  avatar: null,
  selectable_model_options: [],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128000,
  effective_auto_compaction_threshold_tokens: 96000,
  model_parameters: null,
  system_prompt: "Help with research.",
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  runtime_capability: "none",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "not_applicable",
  runtime_add_available: false,
  runtime_remove_available: false,
  toolkit_management_available: true,
  browser_enabled: false,
  terminal_enabled: true,
  infrastructure_terminal_enabled: true,
  workspace_terminal_enabled: true,
  effective_terminal_enabled: true,
  terminal_denied_scope: null,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  routine_check_interval_minutes: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-10-17T00:00:00Z",
  updated_at: "2026-10-17T00:00:00Z",
};
const meta = {
  title: "Personal Tools/Agent Page Layout",
  component: AgentSettingsLayout,
  decorators: [
    (Story) => (
      <Box h="100dvh">
        <Story />
      </Box>
    ),
  ],
  args: {
    handle: "research",
    agent,
    backTarget: "agent",
    children: <Text p="lg">Personal tools for this Agent</Text>,
  },
} satisfies Meta<typeof AgentSettingsLayout>;
export default meta;
type Story = StoryObj<typeof meta>;

export const AgentEntry: Story = {};
export const ConversationReturn: Story = {
  args: { originSessionId: "conversation" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Chat" })).toHaveAttribute(
      "href",
      "/w/research/agents/assistant/sessions/conversation",
    );
    await expect(canvas.queryByRole("tablist")).not.toBeInTheDocument();
  },
};
export const MobileConversationReturn: Story = {
  ...ConversationReturn,
  globals: { viewport: { value: "mobile1", isRotated: false } },
};
export const LongAgentName: Story = {
  args: {
    agent: {
      ...agent,
      name: "An Agent with a long name for cross-Workspace research and personal connection access",
    },
  },
};
