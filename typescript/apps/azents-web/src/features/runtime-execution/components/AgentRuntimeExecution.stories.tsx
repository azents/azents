import {
  agentRuntimeExecutionPolicy,
  configuredRuntimeExecutionStatus,
  emptyRuntimeExecutionRestriction,
  runtimeExecutionAgent,
  runtimeExecutionProfile,
} from "../story-fixtures";
import { AgentRuntimeExecution } from "./AgentRuntimeExecution";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Runtime Execution/Agent Execution Environment",
  component: AgentRuntimeExecution,
  args: {
    handle: "engineering",
    agent: runtimeExecutionAgent,
    state: {
      type: "LOADED",
      policy: agentRuntimeExecutionPolicy,
      profiles: [runtimeExecutionProfile],
      auditEvents: [],
    },
    statusState: {
      type: "LOADED",
      status: configuredRuntimeExecutionStatus,
    },
    profileId: "standard",
    restriction: emptyRuntimeExecutionRestriction,
    saving: false,
    applying: false,
    canSave: true,
    actionError: null,
    actionMessage: null,
    onProfileChange: () => null,
    onRestrictionChange: () => null,
    onSave: () => null,
    onApply: () => null,
  },
} satisfies Meta<typeof AgentRuntimeExecution>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Configured: Story = {};

export const Saving: Story = {
  args: { saving: true },
};

export const RuntimeUnavailable: Story = {
  args: {
    statusState: {
      type: "ERROR",
      message: "Runtime has not been created.",
    },
  },
};

export const VersionConflict: Story = {
  args: {
    actionError:
      '{"code":"stale_execution_policy_version","current_version":5}',
  },
};
