import { Box, rem } from "@mantine/core";
import { WorkspacePanel } from "./WorkspacePanel";
import type {
  AgentWorkspaceServerState,
  WorkspaceEntry,
  WorkspacePanelState,
  WorkspaceProjectPanelState,
} from "../types";
import type { RuntimeSystemMetricsOverviewState } from "@/shared/runtime-metrics/types";
import type { AgentRuntimeLifecyclePresentationResponse } from "@azents/public-client";
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

const readyLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "stable",
  provider: { connection: "connected", resource: "running" },
  runner: { state: "ready" },
  availability: "ready",
  reason_code: null,
  desired_generation: 4,
};

const stoppedLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "stopped",
  convergence: "stable",
  provider: { connection: "connected", resource: "stopped" },
  runner: { state: "disconnected" },
  availability: "stopped",
  reason_code: null,
  desired_generation: 5,
};

const startingLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "starting",
  provider: { connection: "connected", resource: "starting" },
  runner: { state: "disconnected" },
  availability: "transitioning",
  reason_code: "runtime_starting",
  desired_generation: 6,
};

const restartReadyLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "stable",
  provider: { connection: "connected", resource: "starting" },
  runner: { state: "ready" },
  availability: "ready",
  reason_code: null,
  desired_generation: 6,
};

const recoveringLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "recovering",
  provider: { connection: "connected", resource: "running" },
  runner: { state: "starting" },
  availability: "transitioning",
  reason_code: "runner_starting",
  desired_generation: 7,
};

const failedLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "failed",
  provider: { connection: "connected", resource: "failed" },
  runner: { state: "disconnected" },
  availability: "failed",
  reason_code: "runtime_failed",
  desired_generation: 8,
};

const runnerUnavailableLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "stable",
  provider: { connection: "connected", resource: "running" },
  runner: { state: "disconnected" },
  availability: "runner_unavailable",
  reason_code: "runner_disconnected",
  desired_generation: 9,
};

const readyServerState: AgentWorkspaceServerState = {
  lifecycle: readyLifecycle,
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
  runtimeConfiguration: {
    type: "LOADED",
    configuration: {
      status: "applied",
      desired: null,
      applied: null,
    },
  },
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
  directoryLoadStatesByPath: {},
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
      deleteWorktree: true,
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
      deleteWorktree: false,
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
  {
    name: "Session files",
    path: "/workspace/agent/.azents/sessions/change-number-cabbage",
    kind: "directory",
    size: null,
    mediaType: null,
    modifiedAt: null,
    repositoryType: null,
    capabilities: {
      open: true,
      removeProject: false,
      deleteWorktree: false,
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
    source: { type: "session_folder", projectId: null },
  },
];

const readyProjectState: WorkspaceProjectPanelState = {
  type: "READY",
  projects: [],
  registrationDialog: { type: "CLOSED" },
  isRegisteringProject: false,
  isCreatingWorktree: false,
  registerProjectError: null,
  pendingDeleteProjectId: null,
};

const freshMetricsState: RuntimeSystemMetricsOverviewState = {
  type: "READY",
  metrics: {
    summary: "fresh",
    scope: "container",
    cpu: {
      state: "fresh",
      measured_at: "2026-08-24T09:05:00Z",
      used: 780,
      total: 2_000,
      percentage: 39,
    },
    memory: {
      state: "fresh",
      measured_at: "2026-08-24T09:05:00Z",
      used: 1_610_612_736,
      total: 4_294_967_296,
      percentage: 37.5,
    },
    disk: {
      state: "fresh",
      measured_at: "2026-08-24T09:05:00Z",
      used: 9_126_805_913,
      total: 34_359_738_368,
      percentage: 26.56,
    },
    samples: [],
  },
};

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
    metricsState: { type: "LOADING" },
    runtimeSettingsHref: "/w/engineering/agents/agent_01/settings/runtime",
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
    projectState: readyProjectState,
    projectPickerState: { type: "CLOSED" },
    isProjectPickerOpen: false,
    onOpenProjectPicker: noop,
    onCloseProjectPicker: noop,
    onOpenProjectPickerDirectory: noop,
    onSelectProjectPickerDirectory: noop,
    onRefreshProjectPicker: noop,
    onStartRuntimeForProjectPicker: noop,
    onRestartRuntimeForProjectPicker: noop,
    onCloseProjectRegistration: noop,
    onSetProjectRegistrationMode: noop,
    onSetProjectRegistrationStartingRef: noop,
    onSubmitProjectRegistration: noop,
    onRemoveProjectEntry: noop,
    onDeleteWorktreeProjectEntry: noop,
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

export const RuntimeFree = {
  args: {
    state: {
      type: "RUNTIME_FREE",
      runtime: {
        capability: "none",
        capability_version: 1,
        runtime_profile_id: null,
        runtime_profile_selection_version: 1,
        runtime_profile_status: "not_applicable",
        runtime_profile_available: false,
        runtime_profile_availability_reason_code: null,
        removal_impact: null,
        removal: null,
        runtime: null,
        lifecycle: null,
        configuration: null,
        actions: {
          add: true,
          remove: false,
          start: false,
          stop: false,
          restart: false,
          reset: false,
          observe: false,
          use_runner: false,
        },
      },
    },
  },
} satisfies Story;

export const Removing = {
  args: {
    state: {
      type: "REMOVING",
      runtime: {
        ...RuntimeFree.args.state.runtime,
        capability: "removing",
        capability_version: 2,
        runtime_profile_id: "runtime_profile_01",
        runtime_profile_selection_version: 2,
        runtime_profile_status: "configured",
        runtime_profile_available: true,
        removal: {
          id: "removal_01",
          status: "running",
          stage: "deleting_runtime",
          confirmed_at: "2026-08-10T09:00:00Z",
          cleanup_scanned_context_count: 8,
          cleanup_invalidated_context_count: 8,
          product_cleanup_completed_at: "2026-08-10T09:00:02Z",
          physical_deletion_required: true,
          physical_delete_requested_at: "2026-08-10T09:00:03Z",
          physical_delete_acknowledgement_kind: null,
          physical_delete_acknowledged_at: null,
          attempt_count: 1,
          next_attempt_at: null,
          last_error_kind: null,
          last_error_summary: null,
          started_at: "2026-08-10T09:00:01Z",
          completed_at: null,
          updated_at: "2026-08-10T09:00:04Z",
        },
        actions: {
          add: false,
          remove: false,
          start: false,
          stop: false,
          restart: false,
          reset: false,
          observe: false,
          use_runner: false,
        },
      },
    },
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

export const SettingsMobile = {
  args: {
    state: {
      ...readyState,
      server: {
        ...readyState.server,
        actions: {
          ...readyState.server.actions,
          restart: restartAction,
        },
      },
    },
    defaultTab: "settings",
  },
  decorators: [
    (Story) => (
      <Box h="100dvh" w={rem(320)}>
        <Story />
      </Box>
    ),
  ],
} satisfies Story;

export const Metrics = {
  args: {
    state: readyState,
    metricsState: freshMetricsState,
    defaultTab: "metrics",
  },
} satisfies Story;

export const MetricsMobile = {
  args: {
    state: readyState,
    metricsState: freshMetricsState,
    defaultTab: "metrics",
  },
  decorators: [
    (Story) => (
      <Box h="100dvh" w={rem(320)}>
        <Story />
      </Box>
    ),
  ],
} satisfies Story;

export const SettingsRuntimeInactive = {
  args: {
    state: {
      ...readyState,
      runtimeConfiguration: {
        type: "LOADED",
        configuration: {
          status: "waiting_for_recreation",
          desired: null,
          applied: null,
        },
      },
      server: {
        lifecycle: stoppedLifecycle,
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
        lifecycle: stoppedLifecycle,
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
        lifecycle: failedLifecycle,
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
        lifecycle: startingLifecycle,
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

export const RuntimeRestartRefreshing = {
  args: {
    state: {
      ...readyState,
      server: {
        lifecycle: restartReadyLifecycle,
        runtime: {
          type: "STARTING",
          runtime_id: "runtime-1",
          detail: null,
        },
        workspace: readyState.server.workspace,
        actions: {
          start: null,
          stop: stopAction,
          restart: null,
          reset: resetAction,
        },
      },
    },
  },
} satisfies Story;

export const RuntimeRestoring = {
  args: {
    state: {
      ...readyState,
      server: {
        lifecycle: recoveringLifecycle,
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
        lifecycle: runnerUnavailableLifecycle,
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

export const RuntimeErrorWithoutResetAuthority = {
  args: {
    state: {
      ...RuntimeError.args.state,
      server: {
        ...RuntimeError.args.state.server,
        actions: {
          ...RuntimeError.args.state.server.actions,
          reset: null,
        },
      },
    },
  },
} satisfies Story;
