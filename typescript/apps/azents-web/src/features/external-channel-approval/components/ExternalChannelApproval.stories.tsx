import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ExternalChannelApproval } from "./ExternalChannelApproval";
import type { ManagedApprovalRequest } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const pendingRequest: ManagedApprovalRequest = {
  id: "request-1",
  agent_id: "agent-1",
  workspace_id: "workspace-1",
  agent_session_id: null,
  provider: "slack",
  status: "pending",
  principal_id: "principal-1",
  principal_label: "Alice Chen",
  principal_provider_user_id: "U01ALICECHEN",
  resource_label: "#incident-response / deployment thread",
  source_text:
    "Please let the Agent inspect the production rollout and summarize any blockers.",
  original_url: "https://example.slack.com/archives/C1/p1",
  expires_at: "2026-07-23T01:15:00.000Z",
  decided_at: null,
  decision_summary: null,
};

const meta = {
  component: ExternalChannelApproval,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: {
      type: "READY",
      request: pendingRequest,
      submittingDecision: null,
      actionError: null,
    },
    onDecision: fn(),
    onRetry: fn(),
  },
} satisfies Meta<typeof ExternalChannelApproval>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Pending = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /allow for this session/i }),
    );
    await expect(args.onDecision).toHaveBeenCalledWith("allow_session");
  },
} satisfies Story;

export const SubmittingAgentAllow = {
  args: {
    state: {
      type: "READY",
      request: pendingRequest,
      submittingDecision: "allow_agent",
      actionError: null,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await Promise.all(
      canvas
        .getAllByRole("button")
        .map((button) => expect(button).toBeDisabled()),
    );
  },
} satisfies Story;

export const AlreadyAllowed = {
  args: {
    state: {
      type: "READY",
      request: {
        ...pendingRequest,
        status: "allowed",
        agent_session_id: "session-1",
        decided_at: "2026-07-22T01:20:00.000Z",
        decision_summary: "Approved for this Agent.",
      },
      submittingDecision: null,
      actionError: null,
    },
  },
} satisfies Story;

export const Expired = {
  args: {
    state: {
      type: "READY",
      request: {
        ...pendingRequest,
        status: "expired",
        expires_at: "2026-07-21T01:15:00.000Z",
      },
      submittingDecision: null,
      actionError: null,
    },
  },
} satisfies Story;

export const DisconnectedConflict = {
  args: {
    state: {
      type: "READY",
      request: pendingRequest,
      submittingDecision: null,
      actionError: "CONFLICT",
    },
  },
} satisfies Story;

export const OriginalLinkUnavailable = {
  args: {
    state: {
      type: "READY",
      request: { ...pendingRequest, original_url: null },
      submittingDecision: null,
      actionError: null,
    },
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Missing = {
  args: { state: { type: "NOT_FOUND" } },
} satisfies Story;

export const Unauthorized = {
  args: { state: { type: "UNAUTHORIZED" } },
} satisfies Story;

export const ErrorState = {
  args: { state: { type: "ERROR" } },
} satisfies Story;

export const Mobile = {
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(360)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Story;
