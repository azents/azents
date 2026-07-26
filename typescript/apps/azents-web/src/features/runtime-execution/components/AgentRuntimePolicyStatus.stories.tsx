import { AgentRuntimePolicyStatus } from "./AgentRuntimePolicyStatus";
import type { AgentRuntimeExecutionPolicyStatusResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const configured: AgentRuntimeExecutionPolicyStatusResponse = {
  status: "configured",
  configured: {
    profile_id: "standard",
    digest: "configured-digest-0123456789",
    capabilities: [
      { module_id: "container.image_build", version: 1, enabled: false },
      { module_id: "container.run", version: 1, enabled: true },
      { module_id: "container.compose", version: 1, enabled: false },
    ],
    storage_mode: "ephemeral",
    storage_capacity_bytes: 10_737_418_240,
    network_mode: "restricted",
  },
  target: null,
  applied: null,
  desired_generation: 3,
  governing_layers: { "container.image_build.enabled": "workspace" },
  reason_codes: ["explicit_apply_required"],
  required_action: "apply",
};

const meta = {
  title: "Runtime Execution/Agent Runtime Policy Status",
  component: AgentRuntimePolicyStatus,
  args: {
    state: { type: "LOADED", status: configured },
    applying: false,
    onApply: () => null,
  },
} satisfies Meta<typeof AgentRuntimePolicyStatus>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Configured: Story = {};

export const Pending: Story = {
  args: {
    state: {
      type: "LOADED",
      status: {
        ...configured,
        status: "pending",
        target: {
          ...configured.configured,
          desired_generation: 4,
        },
        desired_generation: 4,
        required_action: "wait",
      },
    },
  },
};

export const Applied: Story = {
  args: {
    state: {
      type: "LOADED",
      status: {
        ...configured,
        status: "applied",
        target: {
          ...configured.configured,
          desired_generation: 4,
        },
        applied: {
          ...configured.configured,
          desired_generation: 4,
        },
        desired_generation: 4,
        reason_codes: [],
        required_action: "none",
      },
    },
  },
};

export const Divergent: Story = {
  args: {
    state: {
      type: "LOADED",
      status: {
        ...configured,
        status: "divergent",
        reason_codes: ["applied_pointer_mismatch"],
        required_action: "administrator_action",
      },
    },
  },
};

export const Unavailable: Story = {
  args: {
    state: { type: "ERROR", message: "Runtime has not been created." },
  },
};
