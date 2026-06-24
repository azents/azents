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
  role: "agent" | "subagent";
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
    role: input.role,
    runtime_provider_id: null,
    shell_enabled: input.role !== "subagent",
    memory_enabled: true,
    max_turns: null,
    toolkit_inherit_mode: "all",
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
    role: "agent",
    provider: "openai",
    modelIdentifier: "gpt-5.1",
    lastActiveAt: "2026-05-01T08:30:00.000Z",
  }),
  createAgent({
    id: "agent-operator",
    name: "Release Operator",
    description: "Coordinates branch checks, PR status, and release readiness.",
    enabled: true,
    role: "agent",
    provider: "aws_bedrock",
    modelIdentifier: "global.anthropic.claude-sonnet-4-6",
    lastActiveAt: "2026-05-01T07:10:00.000Z",
  }),
  createAgent({
    id: "agent-archive",
    name: "Archive Helper",
    description: null,
    enabled: false,
    role: "agent",
    provider: "anthropic",
    modelIdentifier: "claude-sonnet-4-5",
    lastActiveAt: "2026-04-16T13:20:00.000Z",
  }),
];

const subagents: EnrichedAgent[] = [
  createAgent({
    id: "subagent-search",
    name: "Web Search",
    description:
      "Finds current references before a parent agent drafts an answer.",
    enabled: true,
    role: "subagent",
    provider: null,
    modelIdentifier: null,
    lastActiveAt: "2026-05-01T06:45:00.000Z",
  }),
  createAgent({
    id: "subagent-reviewer",
    name: "Code Reviewer",
    description: "Checks proposed changes for regressions and missing tests.",
    enabled: true,
    role: "subagent",
    provider: null,
    modelIdentifier: null,
    lastActiveAt: "2026-05-01T05:30:00.000Z",
  }),
  createAgent({
    id: "subagent-painter",
    name: "Painter",
    description:
      "Creates visual drafts when a parent agent needs image concepts.",
    enabled: true,
    role: "subagent",
    provider: null,
    modelIdentifier: null,
    lastActiveAt: "2026-04-30T19:00:00.000Z",
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
      primaryAgents,
      subagents,
      stats: {
        totalAgents: primaryAgents.length,
        enabledAgents: primaryAgents.filter((agent) => agent.enabled).length,
        subagentsCount: subagents.length,
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
    initialView: "subagents",
    initialQuery: "",
    initialShowDisabled: false,
  },
} satisfies Meta<typeof WorkspaceHomeStory>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Subagents = {} satisfies Story;

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
