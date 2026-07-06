import { rem } from "@mantine/core";
import { useState } from "react";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { WorkspaceHome } from "./WorkspaceHome";
import type { WorkspaceHomeContainerOutput } from "../containers/useWorkspaceHomeContainer";
import type { AgentTeamFilter, EnrichedAgent } from "../types";
import type { AgentModelSelection } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

interface WorkspaceHomeStoryProps {
  initialView: AgentTeamFilter;
  initialQuery: string;
  initialShowDisabled: boolean;
}

interface AgentFixtureInput {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  provider: "openai" | "anthropic" | "aws_bedrock" | null;
  modelIdentifier: string | null;
  lastActiveAt: string;
}

function createModelSelection(
  input: AgentFixtureInput,
): AgentModelSelection | null {
  if (input.provider == null || input.modelIdentifier == null) {
    return null;
  }
  return {
    llm_provider_integration_id: `${input.provider}-integration`,
    provider: input.provider,
    model_identifier: input.modelIdentifier,
    model_display_name: input.modelIdentifier,
    model_developer:
      input.provider === "anthropic" || input.provider === "aws_bedrock"
        ? "anthropic"
        : "openai",
    model_family: input.modelIdentifier,
    normalized_capabilities: {
      context_window: { max_input_tokens: 128_000, max_output_tokens: null },
      modalities: { input: ["text"], output: ["text"] },
      tool_calling: { supported: true },
      reasoning: { supported: false, effort_levels: [] },
      built_in_tools: { supported: [] },
      parameters: {},
      compatibility: {},
    },
    model_snapshot: {},
    source_metadata: null,
    last_refreshed_at: input.lastActiveAt,
  };
}

function createAgent(input: AgentFixtureInput): EnrichedAgent {
  const modelSelection = createModelSelection(input);
  return {
    id: input.id,
    name: input.name,
    description: input.description,
    model_selection: modelSelection,
    lightweight_model_selection: null,
    effective_context_window_tokens: 128_000,
    effective_auto_compaction_threshold_tokens: 115_200,
    model_parameters: null,
    system_prompt: null,
    enabled: input.enabled,
    type: "public",
    runtime_provider_id: null,
    shell_enabled: true,
    memory_enabled: true,
    max_turns: null,
    avatar: null,
    created_at: "2026-04-28T09:00:00.000Z",
    updated_at: input.lastActiveAt,
    lastActiveAt: input.lastActiveAt,
    modelSummary:
      modelSelection == null
        ? "Workspace default model"
        : `${modelSelection.provider} · ${modelSelection.model_display_name}`,
  };
}

const primaryAgents: EnrichedAgent[] = [
  createAgent({
    id: "agent-planner",
    name: "Planner",
    description: "Turns rough team requests into scoped implementation plans.",
    enabled: true,
    provider: "openai",
    modelIdentifier: "gpt-5.1",
    lastActiveAt: "2026-05-01T08:30:00.000Z",
  }),
  createAgent({
    id: "agent-operator",
    name: "Release Operator",
    description: "Coordinates branch checks, PR status, and release readiness.",
    enabled: true,
    provider: "aws_bedrock",
    modelIdentifier: "global.anthropic.claude-sonnet-4-6",
    lastActiveAt: "2026-05-01T07:10:00.000Z",
  }),
  createAgent({
    id: "agent-archive",
    name: "Archive Helper",
    description: null,
    enabled: false,
    provider: "anthropic",
    modelIdentifier: "claude-sonnet-4-5",
    lastActiveAt: "2026-04-16T13:20:00.000Z",
  }),
];

function WorkspaceHomeStory({
  initialView,
  initialQuery,
  initialShowDisabled,
}: WorkspaceHomeStoryProps): ReactElement {
  const [view, setView] = useState<AgentTeamFilter>(initialView);
  const [query, setQuery] = useState(initialQuery);
  const [showDisabled, setShowDisabled] = useState(initialShowDisabled);

  const props: WorkspaceHomeContainerOutput = {
    handle: "azents",
    state: {
      type: "READY",
      agents: primaryAgents,
      stats: {
        totalAgents: primaryAgents.length,
        enabledAgents: primaryAgents.filter((agent) => agent.enabled).length,
      },
    },
    view,
    onViewChange: setView,
    query,
    onQueryChange: setQuery,
    showDisabled,
    onShowDisabledChange: setShowDisabled,
    membersCount: 5,
  };

  return <WorkspaceHome {...props} />;
}

const meta = {
  title: "Workspace/WorkspaceHome",
  component: WorkspaceHomeStory,
  decorators: [
    (Story: () => ReactElement): ReactElement => (
      <StorybookCanvas maxWidth={rem(1440)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    initialView: "agents",
    initialQuery: "",
    initialShowDisabled: false,
  },
} satisfies Meta<typeof WorkspaceHomeStory>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Agents = {
  args: {
    initialView: "agents",
  },
} satisfies Story;

export const All = {
  args: {
    initialView: "all",
    initialShowDisabled: true,
  },
} satisfies Story;
