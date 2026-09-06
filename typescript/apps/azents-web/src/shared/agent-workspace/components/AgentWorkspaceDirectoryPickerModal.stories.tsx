import { rem } from "@mantine/core";
import { expect, fireEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentWorkspaceDirectoryPickerModal } from "./AgentWorkspaceDirectoryPickerModal";
import type { ProjectDirectoryPickerState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const readyState = {
  type: "SERVER",
  server: {
    lifecycle: {
      target: "running",
      convergence: "stable",
      provider: { connection: "connected", resource: "running" },
      runner: { state: "ready" },
      availability: "ready",
      reason_code: null,
      desired_generation: 3,
    },
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
      path: "/workspace/agent/azents",
      kind: "directory",
      repositoryType: "git",
    },
    {
      path: "/workspace/agent/research",
      kind: "directory",
      repositoryType: null,
    },
  ],
  isRefreshing: false,
  isStarting: false,
  isRestarting: false,
} satisfies ProjectDirectoryPickerState;

const runtimeUnavailableState = {
  ...readyState,
  server: {
    ...readyState.server,
    lifecycle: {
      ...readyState.server.lifecycle,
      runner: { state: "disconnected" },
      availability: "runner_unavailable",
      reason_code: "runner_disconnected",
    },
    workspace: {
      type: "CONTROL_UNAVAILABLE",
      detail: "The Runtime connection is unavailable.",
      retry_after_ms: 1_000,
    },
  },
} satisfies ProjectDirectoryPickerState;

const mobileOverflowState = {
  ...readyState,
  entries: Array.from({ length: 20 }, (_, index) => ({
    path: `/workspace/agent/project-${String(index + 1).padStart(2, "0")}`,
    kind: "directory" as const,
    repositoryType: index % 3 === 0 ? ("git" as const) : null,
  })),
} satisfies ProjectDirectoryPickerState;

const meta = {
  component: AgentWorkspaceDirectoryPickerModal,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(960)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    opened: true,
    state: { type: "LOADING" },
    onClose: noop,
    onOpenDirectory: noop,
    onSelectDirectory: noop,
    onRefresh: noop,
    onStartRuntime: noop,
    onRestartRuntime: noop,
    runtimeSettingsHref: "/w/engineering/agents/agent-1/runtime",
  },
} satisfies Meta<typeof AgentWorkspaceDirectoryPickerModal>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Loading = {} satisfies Story;

export const RuntimeUnavailable = {
  args: {
    state: runtimeUnavailableState,
  },
} satisfies Story;

export const Ready = {
  args: {
    state: readyState,
  },
} satisfies Story;

export const MobileOverflow = {
  args: {
    state: mobileOverflowState,
  },
  parameters: {
    viewport: {
      defaultViewport: "mobile1",
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    const dialog = await page.findByRole("dialog", {
      name: "Select Project folder",
    });
    const scrollArea = page.getByTestId(
      "agent-workspace-picker-directory-list",
    );
    const viewport = scrollArea.querySelector<HTMLElement>(
      "[data-scrollarea-viewport]",
    );

    await expect(dialog.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      window.innerHeight,
    );
    await expect(viewport).not.toBeNull();
    if (!viewport) {
      return;
    }

    await expect(viewport.scrollHeight).toBeGreaterThan(viewport.clientHeight);
    viewport.scrollTop = viewport.scrollHeight;
    await fireEvent.scroll(viewport);
    await expect(viewport.scrollTop).toBeGreaterThan(0);
  },
} satisfies Story;
