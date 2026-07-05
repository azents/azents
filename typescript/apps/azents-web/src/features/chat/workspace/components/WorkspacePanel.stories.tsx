import { Box } from "@mantine/core";
import { WorkspacePanel } from "./WorkspacePanel";
import type {
  AgentWorkspaceServerState,
  WorkspaceEntry,
  WorkspacePanelState,
} from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const startAction = {
  type: "START_RUNTIME",
  method: "POST",
  path: "",
} as const;

const stopAction = {
  type: "STOP_RUNTIME",
  method: "POST",
  path: "",
} as const;

const resetAction = {
  type: "RESET_RUNTIME",
  method: "POST",
  path: "",
} as const;

const restartAction = {
  type: "RESTART_RUNTIME",
  method: "POST",
  path: "",
} as const;

const readyServerState: AgentWorkspaceServerState = {
  runtime: {
    type: "RUNNING",
    runtime_id: "runtime-1",
    detail: null,
  },
  workspace: {
    type: "READY",
    manifest: {
      root: "/workspace/agent",
      cwd: "/workspace/agent/project",
      entries: [],
      git: null,
    },
  },
  actions: {
    start: null,
    stop: stopAction,
    restart: null,
    reset: resetAction,
  },
};

const readyState: WorkspacePanelState = {
  type: "SERVER",
  server: readyServerState,
  manifest: {
    root: "/workspace/agent",
    cwd: "/workspace/agent/project",
    entries: [
      {
        name: "src",
        path: "/workspace/agent/project/src",
        kind: "directory",
        size: null,
        mediaType: null,
        modifiedAt: null,
      },
      {
        name: "README.md",
        path: "/workspace/agent/project/README.md",
        kind: "file",
        size: 2048,
        mediaType: "text/markdown",
        modifiedAt: "2026-05-01T10:00:00.000Z",
      },
    ],
  },
  directory: {
    path: "/workspace/agent/project",
    entries: [
      {
        name: "components",
        path: "/workspace/agent/project/src/components",
        kind: "directory",
        size: null,
        mediaType: null,
        modifiedAt: null,
      },
      {
        name: "report.json",
        path: "/workspace/agent/project/report.json",
        kind: "file",
        size: 512,
        mediaType: "application/json",
        modifiedAt: "2026-05-01T10:00:00.000Z",
      },
    ],
  },
  directoryEntriesByPath: {
    "/workspace/agent/project": [
      {
        name: "src",
        path: "/workspace/agent/project/src",
        kind: "directory",
        size: null,
        mediaType: null,
        modifiedAt: null,
      },
      {
        name: "README.md",
        path: "/workspace/agent/project/README.md",
        kind: "file",
        size: 2048,
        mediaType: "text/markdown",
        modifiedAt: "2026-05-01T10:00:00.000Z",
      },
    ],
    "/workspace/agent/project/src": [
      {
        name: "components",
        path: "/workspace/agent/project/src/components",
        kind: "directory",
        size: null,
        mediaType: null,
        modifiedAt: null,
      },
      {
        name: "app.tsx",
        path: "/workspace/agent/project/src/app.tsx",
        kind: "file",
        size: 1480,
        mediaType: "text/typescript",
        modifiedAt: "2026-05-01T10:00:00.000Z",
      },
    ],
  },
  fileState: { type: "IDLE" },
  workspaceView: "browser",
  selectedFilePath: null,
  selectedPaths: [],
  selectedEntry: null,
  inspectorState: { type: "IDLE" },
  isRefreshing: false,
  isMutating: false,
  isStarting: false,
  isStopping: false,
  isResetting: false,
};

const projectRootEntries: WorkspaceEntry[] = [
  {
    name: "/workspace/agent/.azents/worktrees/change-number-cabbage/azents",
    path: "/workspace/agent/.azents/worktrees/change-number-cabbage/azents",
    kind: "directory",
    size: null,
    mediaType: null,
    modifiedAt: null,
    repositoryType: "git",
    capabilities: {
      open: true,
      removeProject: true,
      filesystemDelete: false,
      filesystemMove: false,
      filesystemRename: false,
    },
    status: {
      value: "available",
      detail: null,
      checkedAt: "2026-07-04T10:00:00.000Z",
      stale: false,
    },
    source: { type: "session_project", projectId: "project-1" },
  },
  {
    name: "/workspace/agent/home",
    path: "/workspace/agent/home",
    kind: "directory",
    size: null,
    mediaType: null,
    modifiedAt: null,
    repositoryType: null,
    capabilities: {
      open: true,
      removeProject: true,
      filesystemDelete: false,
      filesystemMove: false,
      filesystemRename: false,
    },
    status: {
      value: "available",
      detail: null,
      checkedAt: "2026-07-04T10:00:00.000Z",
      stale: false,
    },
    source: { type: "session_project", projectId: "project-2" },
  },
];

const projectsState: WorkspacePanelState = {
  ...readyState,
  manifest: {
    root: "/workspace/agent",
    cwd: "/workspace/agent",
    entries: projectRootEntries,
  },
  projectBrowserManifest: {
    root: "/workspace/agent",
    activeMode: "projects",
    modes: [
      { id: "projects", label: "Projects", default: true, rootPath: null },
      {
        id: "all_files",
        label: "All files",
        default: false,
        rootPath: "/workspace/agent",
      },
    ],
    entries: projectRootEntries,
    emptyState: null,
  },
  browserMode: "projects",
  directory: {
    path: "/workspace/agent",
    entries: projectRootEntries,
  },
  directoryEntriesByPath: {
    "/workspace/agent": projectRootEntries,
  },
};

const fileState: WorkspacePanelState = {
  ...readyState,
  workspaceView: "preview",
  fileState: {
    type: "LOADED",
    file: {
      path: "/workspace/agent/project/README.md",
      mediaType: "text/markdown",
      size: 2048,
      text: "# Workspace\n\n- Build status: complete\n- Files changed: 3",
      truncated: false,
    },
  },
  selectedFilePath: "/workspace/agent/project/README.md",
  selectedEntry: {
    name: "README.md",
    path: "/workspace/agent/project/README.md",
    kind: "file",
    size: 2048,
    mediaType: "text/markdown",
    modifiedAt: "2026-05-01T10:00:00.000Z",
  },
  inspectorState: {
    type: "LOADED",
    stat: {
      path: "/workspace/agent/project/README.md",
      name: "README.md",
      kind: "file",
      size: 2048,
      mediaType: "text/markdown",
      modifiedAt: "2026-05-01T10:00:00.000Z",
      symlink: false,
      realPath: null,
      resolvedKind: null,
    },
  },
};

const meta = {
  component: WorkspacePanel,
  decorators: [
    (Story) => (
      <Box h="100dvh" maw="40rem">
        <Story />
      </Box>
    ),
  ],
  args: {
    onStartRuntime: noop,
    onStopRuntime: noop,
    onRestartRuntime: noop,
    onResetRuntime: noop,
    onOpenDirectory: noop,
    onOpenFile: noop,
    onShowInfo: noop,
    onBackToBrowser: noop,
    onToggleSelectedPath: noop,
    onClearSelection: noop,
    onRefresh: noop,
    onCreateDirectory: noop,
    onRenamePath: noop,
    onMovePath: noop,
    onDeletePath: noop,
    onBulkMovePaths: noop,
    onBulkDeletePaths: noop,
    getDownloadHref: (path: string): string => `/download?path=${path}`,
    projectPickerState: { type: "CLOSED" },
    isProjectPickerOpen: false,
    onOpenProjectPicker: noop,
    onCloseProjectPicker: noop,
    onOpenProjectPickerDirectory: noop,
    onSelectProjectPickerDirectory: noop,
    onRefreshProjectPicker: noop,
    onStartRuntimeForProjectPicker: noop,
    onRemoveProjectEntry: noop,
    onSetBrowserMode: noop,
  },
} satisfies Meta<typeof WorkspacePanel>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Browser = {
  args: {
    state: readyState,
  },
} satisfies Story;

export const ProjectsWithWorktree = {
  args: {
    state: projectsState,
  },
} satisfies Story;

export const Settings = {
  args: {
    state: readyState,
    defaultTab: "settings",
  },
} satisfies Story;

export const SettingsRuntimeInactive = {
  args: {
    state: {
      ...readyState,
      server: {
        runtime: {
          type: "NOT_STARTED",
          runtime_id: "runtime-1",
          detail: null,
        },
        workspace: {
          type: "UNAVAILABLE",
          reason: "RUNTIME_NOT_RUNNING",
        },
        actions: {
          start: startAction,
          stop: null,
          restart: null,
          reset: null,
        },
      },
      manifest: null,
      selectedEntry: null,
      inspectorState: { type: "IDLE" },
    },
    defaultTab: "settings",
  },
} satisfies Story;

export const Viewer = {
  args: {
    state: fileState,
  },
} satisfies Story;

export const RuntimeInactive = {
  args: {
    state: {
      ...readyState,
      server: {
        runtime: {
          type: "NOT_STARTED",
          runtime_id: "runtime-1",
          detail: null,
        },
        workspace: {
          type: "UNAVAILABLE",
          reason: "RUNTIME_NOT_RUNNING",
        },
        actions: {
          start: startAction,
          stop: null,
          restart: null,
          reset: null,
        },
      },
      manifest: null,
      selectedEntry: null,
      inspectorState: { type: "IDLE" },
    },
  },
} satisfies Story;

export const RuntimeRestoreFailed = {
  args: {
    state: {
      ...readyState,
      server: {
        runtime: {
          type: "RESTORE_FAILED",
          runtime_id: "runtime-1",
          detail: "Runtime checkpoint expired or restore is unavailable.",
        },
        workspace: {
          type: "UNAVAILABLE",
          reason: "RUNTIME_NOT_RUNNING",
        },
        actions: {
          start: startAction,
          stop: null,
          restart: restartAction,
          reset: resetAction,
        },
      },
      manifest: null,
      selectedEntry: null,
      inspectorState: { type: "IDLE" },
    },
  },
} satisfies Story;

export const RuntimeStarting = {
  args: {
    state: {
      ...readyState,
      server: {
        runtime: {
          type: "STARTING",
          runtime_id: "runtime-1",
          detail: null,
        },
        workspace: { type: "CONNECTING" },
        actions: {
          start: null,
          stop: stopAction,
          restart: null,
          reset: null,
        },
      },
      manifest: null,
      selectedEntry: null,
      inspectorState: { type: "IDLE" },
    },
  },
} satisfies Story;

export const RuntimeRestoring = {
  args: {
    state: {
      ...readyState,
      server: {
        runtime: {
          type: "RUNNING",
          runtime_id: "runtime-1",
          detail: null,
        },
        workspace: { type: "CONNECTING" },
        actions: {
          start: null,
          stop: stopAction,
          restart: null,
          reset: null,
        },
      },
      manifest: null,
      selectedEntry: null,
      inspectorState: { type: "IDLE" },
    },
  },
} satisfies Story;

export const RuntimeError = {
  args: {
    state: {
      ...readyState,
      server: {
        runtime: {
          type: "RUNNING",
          runtime_id: "runtime-1",
          detail: null,
        },
        workspace: {
          type: "CONTROL_UNAVAILABLE",
          detail:
            "Runtime is temporarily unavailable. Please try again in a moment.",
          retry_after_ms: 1000,
        },
        actions: {
          start: null,
          stop: stopAction,
          restart: restartAction,
          reset: resetAction,
        },
      },
      manifest: null,
      selectedEntry: null,
      inspectorState: { type: "IDLE" },
    },
  },
} satisfies Story;
