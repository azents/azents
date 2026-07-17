import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RunRetryCard } from "./RunRetryCard";
import type { ChatLiveRunRetryState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const liveRetry: ChatLiveRunRetryState = {
  status: "waiting",
  lastErrorMessage:
    "Model provider error: The provider is temporarily rate limited.",
  failedAttemptCount: 2,
  maxRetries: 10,
  backoffSeconds: 10,
  nextRetryAt: new Date(Date.now() + 45_000).toISOString(),
  attempts: [],
};

const meta = {
  title: "chat/RunRetryCard",
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(860)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta;

export default meta;

type Story = StoryObj<typeof meta>;

export const LiveWaitingCountdown = {
  render: () => <RunRetryCard variant="live" retry={liveRetry} phase="idle" />,
} satisfies Story;

export const LiveModelCall = {
  render: () => (
    <RunRetryCard
      variant="live"
      retry={{ ...liveRetry, status: "running" }}
      phase="waiting_for_model"
    />
  ),
} satisfies Story;

export const StoppedRetryAvailable = {
  render: () => (
    <RunRetryCard
      variant="stopped"
      recoveryKind="provider_failure"
      message="Model provider error: The provider connection was interrupted."
      canRetry={true}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const GenericStoppedRetryAvailable = {
  render: () => (
    <RunRetryCard
      variant="stopped"
      recoveryKind="stopped"
      message="Execution stopped."
      canRetry={true}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const StoppedRetryPending = {
  render: () => (
    <RunRetryCard
      variant="stopped"
      recoveryKind="provider_failure"
      message="Model provider error: The provider connection was interrupted."
      canRetry={true}
      isRetryPending={true}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const TerminalRetryAvailable = {
  render: () => (
    <RunRetryCard
      variant="terminal"
      message="Model provider error: The request was rejected after all retries."
      canRetry={true}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const TerminalLongMessage = {
  render: () => (
    <RunRetryCard
      variant="terminal"
      message={`Model provider error: ${"The provider could not process this bounded request detail. ".repeat(14)}`}
      canRetry={true}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const NarrowStoppedRecovery = {
  parameters: {
    viewport: { defaultViewport: "mobile1" },
  },
  render: () => (
    <RunRetryCard
      variant="stopped"
      recoveryKind="provider_failure"
      message="Model provider error: The request stopped before the provider completed it."
      canRetry={true}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;
