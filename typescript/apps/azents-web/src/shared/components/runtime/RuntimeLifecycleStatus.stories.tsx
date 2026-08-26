import { Box, rem } from "@mantine/core";
import { RuntimeLifecycleStatus } from "./RuntimeLifecycleStatus";
import type { AgentRuntimeLifecyclePresentationResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const readyLifecycle: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "stable",
  provider: {
    connection: "connected",
    resource: "running",
  },
  runner: {
    state: "ready",
  },
  availability: "ready",
  reason_code: null,
  desired_generation: 8,
};

const meta = {
  component: RuntimeLifecycleStatus,
  decorators: [
    (Story) => (
      <Box maw={rem(760)}>
        <Story />
      </Box>
    ),
  ],
} satisfies Meta<typeof RuntimeLifecycleStatus>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Ready = {
  args: {
    lifecycle: readyLifecycle,
  },
} satisfies Story;

export const ReadyWithoutHostControls = {
  args: {
    lifecycle: {
      ...readyLifecycle,
      provider: {
        connection: "disconnected",
        resource: "unknown",
      },
    },
  },
} satisfies Story;

export const Stopping = {
  args: {
    compact: true,
    lifecycle: {
      ...readyLifecycle,
      target: "stopped",
      convergence: "stopping",
      provider: {
        connection: "connected",
        resource: "stopping",
      },
      availability: "transitioning",
      reason_code: "runtime_stopping",
    },
  },
} satisfies Story;

export const ConnectionUnavailable = {
  args: {
    compact: true,
    lifecycle: {
      ...readyLifecycle,
      runner: {
        state: "disconnected",
      },
      availability: "runner_unavailable",
      reason_code: "runner_disconnected",
    },
  },
} satisfies Story;
