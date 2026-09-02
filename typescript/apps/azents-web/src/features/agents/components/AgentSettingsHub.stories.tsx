import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentSettingsHub } from "./AgentSettingsHub";
import type { AgentResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  id: "agent_01",
  name: "Release Operator",
  description: "Coordinates release checklists and CI follow-up.",
  type: "private",
  enabled: true,
  avatar: null,
  model_selection: null,
  lightweight_model_selection: null,
  selectable_model_options: [],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128000,
  effective_auto_compaction_threshold_tokens: 96000,
  model_parameters: null,
  system_prompt: "Help the workspace team with release operations.",
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  runtime_capability: "none",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "not_applicable",
  runtime_add_available: false,
  runtime_remove_available: false,
  terminal_enabled: true,
  shell_enabled: true,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-06-25T08:00:00Z",
  updated_at: "2026-06-25T08:00:00Z",
};

const meta = {
  component: AgentSettingsHub,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(920)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agent,
    automaticProjectsCount: 2,
  },
} satisfies Meta<typeof AgentSettingsHub>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Loaded = {} satisfies Story;

export const ManagedRuntime = {
  args: {
    agent: {
      ...agent,
      runtime_profile_id: "runtime_profile_01",
      runtime_profile_available: true,
      runtime_profile_availability_reason_code: null,
      runtime_capability: "managed",
      runtime_capability_version: 2,
      runtime_profile_configuration_status: "configured",
      runtime_add_available: false,
      runtime_remove_available: true,
      terminal_enabled: true,
    },
  },
} satisfies Story;

export const RemovingRuntime = {
  args: {
    agent: {
      ...ManagedRuntime.args.agent,
      runtime_capability: "removing",
      runtime_capability_version: 3,
      runtime_add_available: false,
      runtime_remove_available: false,
      terminal_enabled: true,
    },
  },
} satisfies Story;

export const DisabledAgent = {
  args: {
    agent: {
      ...agent,
      enabled: false,
      shell_enabled: false,
      memory_enabled: false,
      model_selection: null,
    },
  },
} satisfies Story;
