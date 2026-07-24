import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentAutomaticProjects } from "./AgentAutomaticProjects";
import type {
  AutomaticProjectRow,
  AutomaticProjectsState,
} from "../automaticProjects";
import type { ProjectDirectoryPickerState } from "@/features/agent-workspace/types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const rows: AutomaticProjectRow[] = [
  {
    path: "/workspace/agent/payment-api",
    name: "payment-api",
    status: "available",
    detail: null,
  },
  {
    path: "/workspace/agent/order-service",
    name: "order-service",
    status: "available",
    detail: null,
  },
];

const closedPickerState: ProjectDirectoryPickerState = { type: "CLOSED" };
const readyPickerState: ProjectDirectoryPickerState = {
  type: "SERVER",
  server: {
    runtime: {
      type: "RUNNING",
      runtime_id: "runtime-1",
      detail: null,
    },
    workspace: {
      type: "READY",
      manifest: {
        root: "/workspace/agent",
        cwd: "/workspace/agent",
        entries: [],
        git: null,
      },
    },
    actions: {
      start: null,
      stop: null,
      restart: null,
      reset: null,
    },
  },
  currentPath: "/workspace/agent",
  entries: [
    {
      path: "/workspace/agent/payment-api",
      kind: "directory",
      repositoryType: "git",
    },
    {
      path: "/workspace/agent/order-service",
      kind: "directory",
      repositoryType: null,
    },
  ],
  isRefreshing: false,
  isStarting: false,
};

const commonArgs = {
  isProjectPickerOpen: false,
  pickerState: closedPickerState,
  onAddProject: () => {},
  onCloseProjectPicker: () => {},
  onOpenProjectPickerDirectory: () => {},
  onSelectProjectPickerDirectory: () => {},
  onRefreshProjectPicker: () => {},
  onStartRuntimeForProjectPicker: () => {},
  onRemoveProject: () => {},
  onMoveProject: () => {},
  onSave: () => Promise.resolve(),
  onRetrySave: () => Promise.resolve(),
  onReloadLatest: () => Promise.resolve(),
};

const meta = {
  component: AgentAutomaticProjects,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(920)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    ...commonArgs,
    state: {
      type: "CLEAN",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
    } satisfies AutomaticProjectsState,
  },
} satisfies Meta<typeof AgentAutomaticProjects>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Loading = {
  args: {
    state: { type: "LOADING" },
  },
} satisfies Story;

export const Empty = {
  args: {
    state: { type: "EMPTY", revision: 1, updatedAt: "2026-07-24T00:00:00Z" },
  },
} satisfies Story;

export const Populated = {} satisfies Story;

export const Dirty = {
  args: {
    state: {
      type: "DIRTY",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
    },
  },
} satisfies Story;

export const Saving = {
  args: {
    state: {
      type: "SAVING",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
    },
  },
} satisfies Story;

export const MissingPath = {
  args: {
    state: {
      type: "MISSING",
      revision: 3,
      rows: [
        {
          path: "/workspace/agent/payment-api",
          name: "payment-api",
          status: "missing",
          detail: null,
        },
      ],
      updatedAt: "2026-07-24T00:00:00Z",
      message: "",
      dirty: false,
    },
  },
} satisfies Story;

export const RevisionConflict = {
  args: {
    state: {
      type: "CONFLICT",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
      message: "Another administrator saved a newer project list.",
    },
  },
} satisfies Story;

export const RuntimeUnavailable = {
  args: {
    state: {
      type: "RUNTIME_UNAVAILABLE",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
      message: "Start the Runtime before saving non-empty projects.",
    },
  },
} satisfies Story;

export const ValidationError = {
  args: {
    state: {
      type: "VALIDATION_ERROR",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
      message: "The selected directory is no longer available.",
      path: "/workspace/agent/order-service",
    },
  },
} satisfies Story;

export const EditorError = {
  args: {
    state: {
      type: "EDITOR_ERROR",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
      message: "The project policy could not be saved.",
    },
  },
} satisfies Story;

export const PickerLoading = {
  args: {
    isProjectPickerOpen: true,
    pickerState: { type: "LOADING" },
  },
} satisfies Story;

export const PickerError = {
  args: {
    isProjectPickerOpen: true,
    pickerState: {
      type: "ERROR",
      message: "The Agent Workspace is unavailable.",
    },
  },
} satisfies Story;

export const PickerReady = {
  args: {
    isProjectPickerOpen: true,
    pickerState: readyPickerState,
  },
} satisfies Story;

export const MobileDirty = {
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(390)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: {
      type: "DIRTY",
      revision: 3,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
    },
  },
} satisfies Story;
