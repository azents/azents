import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentMemorySettings } from "./AgentMemorySettings";
import type { AgentResponse, MemoryResponse } from "@azents/public-client";
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
  effective_context_window_tokens: 128000,
  effective_auto_compaction_threshold_tokens: 96000,
  model_parameters: null,
  system_prompt: "Help the workspace team with release operations.",
  runtime_provider_id: null,
  shell_enabled: true,
  memory_enabled: true,
  max_turns: null,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-06-25T08:00:00Z",
  updated_at: "2026-06-25T08:00:00Z",
};

const noop = (): void => {};

const memories: MemoryResponse[] = [
  {
    id: "mem_01",
    agent_id: agent.id,
    user_id: null,
    scope: "agent",
    type: "project",
    name: "release-checklist",
    description: "Release checklist conventions for this workspace.",
    content:
      "Always verify CI, migrations, and rollback notes before announcing a release.",
    created_at: "2026-06-25T08:00:00Z",
    updated_at: "2026-06-25T08:00:00Z",
  },
  {
    id: "mem_02",
    agent_id: agent.id,
    user_id: null,
    scope: "agent",
    type: "feedback",
    name: "pr-language",
    description: "PR titles and bodies must be written in English.",
    content:
      "Use concise English for PR titles, descriptions, and review comments.",
    created_at: "2026-06-25T08:00:00Z",
    updated_at: "2026-06-25T08:00:00Z",
  },
];

const meta = {
  component: AgentMemorySettings,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(980)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agent,
    memoryEnabled: true,
    scope: "agent",
    query: "",
    listState: { type: "LOADED", memories },
    draftState: null,
    actionError: null,
    saving: false,
    deletingId: null,
    togglingMemory: false,
    onScopeChange: noop,
    onQueryChange: noop,
    onMemoryEnabledChange: noop,
    onStartCreate: noop,
    onStartEdit: noop,
    onCancelDraft: noop,
    onDraftChange: noop,
    onSaveDraft: noop,
    onDeleteMemory: noop,
  },
} satisfies Meta<typeof AgentMemorySettings>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Loaded = {} satisfies Story;

export const Empty = {
  args: {
    listState: { type: "LOADED", memories: [] },
  },
} satisfies Story;

export const Editing = {
  args: {
    draftState: {
      type: "edit",
      memoryId: "mem_01",
      draft: {
        type: "project",
        name: "release-checklist",
        description: "Release checklist conventions for this workspace.",
        content:
          "Always verify CI, migrations, and rollback notes before announcing a release.",
      },
    },
  },
} satisfies Story;
