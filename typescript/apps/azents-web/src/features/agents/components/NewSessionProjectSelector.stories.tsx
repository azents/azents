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
    workspaceItems: [
      {
        id: "existing-azents",
        type: "existing_project",
        path: "/workspace/agent/azents",
      },
    ],
    activeWorktreeItemId: null,
    gitRefPreviewState: { type: "IDLE" },
    projectPresetState: { type: "READY", presets },
    onAddPresetProject: () => {},
    onAddWorktreeProject: () => {},
    onActivateWorktreeItem: () => {},
    onSetWorktreeStartingRef: () => {},
    onRemoveWorkspaceItem: () => {},
    onOpenProjectPicker: () => {},
  },
} satisfies Meta<typeof NewSessionProjectSelector>;

export default meta;

type Story = StoryObj<typeof meta>;

export const ExistingProject = {} satisfies Story;

export const Empty = {
  args: {
    workspaceItems: [],
  },
} satisfies Story;

export const MixedWorkspaces = {
  args: {
    workspaceItems: [
      {
        id: "existing-azents",
        type: "existing_project",
        path: "/workspace/agent/azents",
      },
      {
        id: "worktree-api",
        type: "git_worktree",
        sourceProjectPath: "/workspace/agent/azents/python/apps/azents",
        startingRef: "refs/heads/main",
      },
    ],
    activeWorktreeItemId: "worktree-api",
    gitRefPreviewState: { type: "READY", refs },
  },
} satisfies Story;

export const WorktreeLoadingBranches = {
  args: {
    workspaceItems: [
      {
        id: "worktree-azents",
        type: "git_worktree",
        sourceProjectPath: "/workspace/agent/azents",
        startingRef: null,
      },
    ],
    activeWorktreeItemId: "worktree-azents",
    gitRefPreviewState: { type: "LOADING" },
  },
} satisfies Story;

export const WorktreeBranchError = {
  args: {
    workspaceItems: [
      {
        id: "worktree-azents",
        type: "git_worktree",
        sourceProjectPath: "/workspace/agent/azents",
        startingRef: null,
      },
    ],
    activeWorktreeItemId: "worktree-azents",
    gitRefPreviewState: { type: "ERROR", message: "Git ref preview failed." },
  },
} satisfies Story;

export const WorktreeNoLocalBranches = {
  args: {
    workspaceItems: [
      {
        id: "worktree-azents",
        type: "git_worktree",
        sourceProjectPath: "/workspace/agent/azents",
        startingRef: null,
      },
    ],
    activeWorktreeItemId: "worktree-azents",
    gitRefPreviewState: { type: "READY", refs: [] },
  },
} satisfies Story;
