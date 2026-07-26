import {
  emptyRuntimeExecutionRestriction,
  runtimeExecutionProfile,
  workspaceRuntimeExecutionPolicy,
} from "../story-fixtures";
import { WorkspaceRuntimeExecution } from "./WorkspaceRuntimeExecution";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Runtime Execution/Workspace",
  component: WorkspaceRuntimeExecution,
  args: {
    state: {
      type: "LOADED",
      policy: workspaceRuntimeExecutionPolicy,
      profiles: [runtimeExecutionProfile],
      auditEvents: [],
      canEdit: true,
    },
    restriction: emptyRuntimeExecutionRestriction,
    allowedProfileIds: ["standard"],
    saving: false,
    canSave: true,
    hasUnsupportedSelection: false,
    actionError: null,
    onRestrictionChange: () => null,
    onToggleProfile: () => null,
    onSave: () => null,
  },
} satisfies Meta<typeof WorkspaceRuntimeExecution>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Editable: Story = {};

export const ReadOnly: Story = {
  args: {
    state: {
      type: "LOADED",
      policy: workspaceRuntimeExecutionPolicy,
      profiles: [runtimeExecutionProfile],
      auditEvents: [],
      canEdit: false,
    },
  },
};

export const Empty: Story = {
  args: {
    state: {
      type: "LOADED",
      policy: workspaceRuntimeExecutionPolicy,
      profiles: [],
      auditEvents: [],
      canEdit: true,
    },
    allowedProfileIds: [],
  },
};

export const Error: Story = {
  args: {
    state: { type: "ERROR", message: "Runtime Execution is unavailable." },
  },
};
