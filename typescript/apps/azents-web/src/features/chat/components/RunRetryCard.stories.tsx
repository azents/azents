import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RunRetryCard } from "./RunRetryCard";
import type { ChatLiveRunRetryState, FailedRunFailureMetadata } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const attempts = [
  {
    attemptNumber: 1,
    userMessage: "The model provider returned a temporary rate limit.",
    errorType: "RateLimitError",
    source: "model_provider",
    failedAt: "2026-05-01T10:00:00.000Z",
    backoffSeconds: 5,
    nextRetryAt: "2026-05-01T10:00:05.000Z",
    retryability: "transient",
    failureCode: "provider_rate_limited",
    truncated: false,
  },
  {
    attemptNumber: 2,
    userMessage: "The retry also hit the provider retry window.",
    errorType: "RateLimitError",
    source: "model_provider",
    failedAt: "2026-05-01T10:00:05.000Z",
    backoffSeconds: 10,
    nextRetryAt: "2026-05-01T10:00:15.000Z",
    retryability: "transient",
    failureCode: "provider_rate_limited",
    truncated: false,
  },
];

const liveRetry: ChatLiveRunRetryState = {
  status: "waiting",
  lastErrorMessage: "The provider is temporarily rate limited.",
  failedAttemptCount: 2,
  maxRetries: 5,
  backoffSeconds: 10,
  nextRetryAt: new Date(Date.now() + 45_000).toISOString(),
  attempts,
};

const terminalFailure: FailedRunFailureMetadata = {
  kind: "failed_run",
  finalization_reason: "retry_exhausted",
  failed_attempt_count: 5,
  max_retries: 5,
  last_error_type: "RateLimitError",
  retryability: "transient",
  failure_code: "provider_rate_limited",
  action_hint: "Check provider status or try again later.",
  attempts,
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

export const TerminalRetryAvailable = {
  render: () => (
    <RunRetryCard
      variant="terminal"
      message="The run failed after all retry attempts were exhausted."
      failure={terminalFailure}
      canRetry={true}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const TerminalRetryPending = {
  render: () => (
    <RunRetryCard
      variant="terminal"
      message="The run failed after all retry attempts were exhausted."
      failure={terminalFailure}
      canRetry={true}
      isRetryPending={true}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const TerminalLongMessage = {
  render: () => (
    <RunRetryCard
      variant="terminal"
      message={`Model call failed (500): litellm.InternalServerError: OpenAIException - <html><head><meta name="viewport" content="width=device-width, initial-scale=1" /><style>body{font-family:Arial,Helvetica,sans-serif}.container{align-items:center;display:flex;flex-direction:column;gap:2rem;height:100%;justify-content:center;width:100%}@keyframes enlarge-appear{0%{opacity:0;transform:scale(75%) rotate(-90deg)}to{opacity:1;transform:scale(100%) rotate(0deg)}}.logo{color:#8e8ea0}.scale-appear{animation:enlarge-appear .4s ease-out}</style></head><body><div class="container">Provider error response</div></body></html>`}
      failure={terminalFailure}
      canRetry={true}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const TerminalRetryUnavailable = {
  render: () => (
    <RunRetryCard
      variant="terminal"
      message="The run failed after all retry attempts were exhausted."
      failure={terminalFailure}
      canRetry={false}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;

export const TerminalNonRetryable = {
  render: () => (
    <RunRetryCard
      variant="terminal"
      message="The provider rejected the request as non-retryable."
      failure={{
        ...terminalFailure,
        finalization_reason: "non_retryable",
        retryability: "non_retryable",
        failed_attempt_count: 1,
        max_retries: 5,
        action_hint: "Update the request and send a new message.",
      }}
      canRetry={false}
      isRetryPending={false}
      onRetry={() => {}}
    />
  ),
} satisfies Story;
