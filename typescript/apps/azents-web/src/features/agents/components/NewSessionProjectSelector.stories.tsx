import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { NewSessionProjectSelector } from "./NewSessionProjectSelector";
import type {
  AgentProjectPresetResponse,
  GitRefEntryResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const presets: AgentProjectPresetResponse[] = [
  {
    id: "preset_azents",
    path: "/workspace/agent/azents",
    created_at: "2026-07-04T01:00:00Z",
    updated_at: "2026-07-04T01:00:00Z",
  },
  {
    id: "preset_api",
    path: "/workspace/agent/azents/python/apps/azents",
    created_at: "2026-07-04T01:05:00Z",
    updated_at: "2026-07-04T01:05:00Z",
  },
];

const refs: GitRefEntryResponse[] = [
  {
    name: "main",
    ref: "refs/heads/main",
    type: "branch",
    target: "abc123",
    default: true,
  },
  {
    name: "feature/session-init",
    ref: "refs/heads/feature/session-init",
    type: "branch",
    target: "def456",
    default: false,
  },
  {
    name: "v1.0.0",
    ref: "refs/tags/v1.0.0",
    type: "tag",
    target: "fedcba",
    default: false,
  },
];

const meta = {
  component: NewSessionProjectSelector,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    selectedProjectPaths: ["/workspace/agent/azents"],
    workspaceMode: { type: "existing_projects" },
    gitRefPreviewState: { type: "IDLE" },
    projectPresetState: { type: "READY", presets },
    onSelectExistingProjectsMode: () => {},
    onSelectGitWorktreeMode: () => {},
    onAddPresetProject: () => {},
    onSetWorktreeSourceProject: () => {},
    onSetWorktreeStartingRef: () => {},
    onRemoveProject: () => {},
    onOpenProjectPicker: () => {},
  },
} satisfies Meta<typeof NewSessionProjectSelector>;

export default meta;

type Story = StoryObj<typeof meta>;

export const ExistingProjects = {} satisfies Story;

export const ExistingProjectsEmpty = {
  args: {
    selectedProjectPaths: [],
  },
} satisfies Story;

export const GitWorktreeNeedsSource = {
  args: {
    selectedProjectPaths: [],
    workspaceMode: {
      type: "git_worktree",
      sourceProjectPath: null,
      startingRef: null,
    },
    gitRefPreviewState: { type: "IDLE" },
  },
} satisfies Story;

export const GitWorktreeLoadingRefs = {
  args: {
    workspaceMode: {
      type: "git_worktree",
      sourceProjectPath: "/workspace/agent/azents",
      startingRef: null,
    },
    gitRefPreviewState: { type: "LOADING" },
  },
} satisfies Story;

export const GitWorktreeReady = {
  args: {
    workspaceMode: {
      type: "git_worktree",
      sourceProjectPath: "/workspace/agent/azents",
      startingRef: "refs/heads/main",
    },
    gitRefPreviewState: { type: "READY", refs },
  },
} satisfies Story;

export const GitWorktreeRefError = {
  args: {
    workspaceMode: {
      type: "git_worktree",
      sourceProjectPath: "/workspace/agent/azents",
      startingRef: null,
    },
    gitRefPreviewState: { type: "ERROR", message: "Git ref preview failed." },
  },
} satisfies Story;
