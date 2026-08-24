import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeSystemMetricsOverview } from "./RuntimeSystemMetricsOverview";
import type { AgentRuntimeSystemMetricsResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const samples: AgentRuntimeSystemMetricsResponse["samples"] = [
  {
    measured_at: "2026-08-24T09:00:00Z",
    scope: "container",
    cpu: { availability: "unavailable", used: null, total: null },
    memory: {
      availability: "available",
      used: 1_073_741_824,
      total: 4_294_967_296,
    },
    disk: {
      availability: "available",
      used: 8_589_934_592,
      total: 34_359_738_368,
    },
  },
  {
    measured_at: "2026-08-24T09:01:00Z",
    scope: "container",
    cpu: { availability: "available", used: 420, total: 2_000 },
    memory: {
      availability: "available",
      used: 1_342_177_280,
      total: 4_294_967_296,
    },
    disk: {
      availability: "available",
      used: 8_697_308_774,
      total: 34_359_738_368,
    },
  },
  {
    measured_at: "2026-08-24T09:04:00Z",
    scope: "container",
    cpu: { availability: "available", used: 1_120, total: 2_000 },
    memory: {
      availability: "unavailable",
      used: null,
      total: null,
    },
    disk: {
      availability: "available",
      used: 8_912_057_344,
      total: 34_359_738_368,
    },
  },
  {
    measured_at: "2026-08-24T09:05:00Z",
    scope: "container",
    cpu: { availability: "available", used: 780, total: 2_000 },
    memory: {
      availability: "available",
      used: 1_610_612_736,
      total: 4_294_967_296,
    },
    disk: {
      availability: "available",
      used: 9_126_805_913,
      total: 34_359_738_368,
    },
  },
];

const freshMetrics: AgentRuntimeSystemMetricsResponse = {
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
  samples,
};

const meta = {
  component: RuntimeSystemMetricsOverview,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1040)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: { type: "READY", metrics: freshMetrics },
  },
} satisfies Meta<typeof RuntimeSystemMetricsOverview>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Fresh = {} satisfies Story;

export const PartialFirstSample = {
  args: {
    state: {
      type: "READY",
      metrics: {
        ...freshMetrics,
        summary: "partial",
        cpu: {
          state: "unavailable",
          measured_at: "2026-08-24T09:00:00Z",
          used: null,
          total: null,
          percentage: null,
        },
        samples: samples.slice(0, 1),
      },
    },
  },
} satisfies Story;

export const Stale = {
  args: {
    state: {
      type: "READY",
      metrics: {
        ...freshMetrics,
        summary: "stale",
        cpu: { ...freshMetrics.cpu, state: "stale" },
        memory: { ...freshMetrics.memory, state: "stale" },
        disk: { ...freshMetrics.disk, state: "stale" },
      },
    },
  },
} satisfies Story;

export const RuntimeStopped = {
  args: {
    state: {
      type: "READY",
      metrics: {
        ...freshMetrics,
        summary: "stopped",
        cpu: { ...freshMetrics.cpu, state: "stopped" },
        memory: { ...freshMetrics.memory, state: "stopped" },
        disk: { ...freshMetrics.disk, state: "stopped" },
      },
    },
  },
} satisfies Story;

export const Unsupported = {
  args: {
    state: {
      type: "READY",
      metrics: {
        summary: "unsupported",
        scope: null,
        cpu: {
          state: "unsupported",
          measured_at: null,
          used: null,
          total: null,
          percentage: null,
        },
        memory: {
          state: "unsupported",
          measured_at: null,
          used: null,
          total: null,
          percentage: null,
        },
        disk: {
          state: "unsupported",
          measured_at: null,
          used: null,
          total: null,
          percentage: null,
        },
        samples: [],
      },
    },
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Error = {
  args: {
    state: {
      type: "ERROR",
      message: "The metrics service is temporarily unavailable.",
    },
  },
} satisfies Story;
