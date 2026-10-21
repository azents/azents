import { Box } from "@mantine/core";
import { fn } from "storybook/test";
import { ProjectPanelView } from "./ProjectPanel";
import type { WorkspaceProjectPanelState } from "../types";
import type { ProjectDirectoryPickerState } from "./WorkspaceDirectoryPickerModal";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};
const noopPath = (): void => {};

const closedProjectPickerState: ProjectDirectoryPickerState = {
  type: "CLOSED",
};

const readyProjectState: WorkspaceProjectPanelState = {
  type: "READY",
  projects: [
    {
      id: "project-1",
      path: "/workspace/agent/project",
      created_at: "2026-05-09T00:00:00Z",
      updated_at: "2026-05-09T00:00:00Z",
    },
    {
      id: "project-2",
      path: "/workspace/agent/reporting",
      created_at: "2026-05-09T00:02:00Z",
      updated_at: "2026-05-09T00:02:00Z",
    },
  ],
  registrationDialog: { type: "CLOSED" },
  isRegisteringProject: false,
  isCreatingWorktree: false,
  registerProjectError: null,
  pendingDeleteProjectId: null,
};

const meta = {
  component: ProjectPanelView,
  tags: ["ci-contract"],
  decorators: [
    (Story) => (
      <Box h="100dvh" maw="40rem" p="md">
        <Story />
      </Box>
    ),
  ],
  args: {
    projectState: readyProjectState,
    projectPickerState: closedProjectPickerState,
    isProjectPickerOpen: false,
    onOpenProjectPicker: noop,
    onCloseProjectPicker: noop,
    onOpenProjectPickerDirectory: noopPath,
    onSelectProjectPickerDirectory: noopPath,
    onRefreshProjectPicker: noop,
    onStartRuntimeForProjectPicker: noop,
    onRestartRuntimeForProjectPicker: noop,
    onCloseProjectRegistration: noop,
    onSetProjectRegistrationMode: noop,
    onSetProjectRegistrationStartingRef: noop,
    onSubmitProjectRegistration: noop,
    onDeleteProject: noop,
    deleteProjectId: null,
    setDeleteProjectId: fn(),
    handleConfirmDeleteProject: fn(),
  },
} satisfies Meta<typeof ProjectPanelView>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Ready = {} satisfies Story;
export const ConfirmDeletion = {
  args: { deleteProjectId: "project-1" },
} satisfies Story;

export const Loading = {
  args: {
    projectState: { type: "LOADING" },
  },
} satisfies Story;

export const Error = {
  args: {
    projectState: {
      type: "ERROR",
      message: "Project requests failed. Please try again in a moment.",
    },
  },
} satisfies Story;

export const Empty = {
  args: {
    projectState: {
      ...readyProjectState,
      projects: [],
    },
  },
} satisfies Story;
