import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeWebConfirmation } from "./RuntimeWebConfirmation";
import type { RuntimeWebServiceResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const pendingService: RuntimeWebServiceResponse = {
  endpoint: {
    id: "endpoint000000000000000000000000",
    port: 4173,
    label: "Documentation preview",
    url: "https://docs-preview.services.example.com",
    configuration_state: "configured",
    authority_revision: 2,
    close_barrier: 0,
    created_at: "2026-09-12T00:00:00Z",
    updated_at: "2026-09-12T00:05:00Z",
  },
  current_request: {
    id: "request0000000000000000000000000",
    requester_kind: "agent",
    state: "pending",
    revision: 1,
    label: "Documentation preview",
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-09-12T00:05:00Z",
    updated_at: "2026-09-12T00:05:00Z",
  },
  current_cycle: null,
  active: false,
  duration_seconds: 3600,
  duration_configuration_revision: 2,
  observed_at: "2026-09-12T00:05:00Z",
};

const meta = {
  component: RuntimeWebConfirmation,
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
      service: pendingService,
      action: null,
      actionError: null,
    },
    onApprove: fn(),
    onReject: fn(),
    onCancel: fn(),
    onClose: fn(),
    onRetry: fn(),
  },
} satisfies Meta<typeof RuntimeWebConfirmation>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Pending = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Approve for 60 minutes" }),
    );
    await expect(args.onApprove).toHaveBeenCalled();
  },
} satisfies Story;

export const Active = {
  args: {
    state: {
      type: "READY",
      service: {
        ...pendingService,
        current_request: null,
        current_cycle: {
          id: "cycle00000000000000000000000000",
          request_id: "request0000000000000000000000000",
          duration_seconds: 3600,
          duration_configuration_revision: 2,
          approved_at: "2026-09-12T00:10:00Z",
          expires_at: "2026-09-12T01:10:00Z",
          close_barrier: 0,
          ended_at: null,
          end_reason: null,
        },
        active: true,
      },
      action: null,
      actionError: null,
    },
  },
} satisfies Story;

export const Stale = {
  args: {
    state: {
      type: "READY",
      service: { ...pendingService, current_request: null },
      action: null,
      actionError: null,
    },
  },
} satisfies Story;

export const ActionError = {
  args: {
    state: {
      type: "READY",
      service: pendingService,
      action: null,
      actionError: "The service state changed. Review the current request.",
    },
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const ErrorState = {
  args: {
    state: { type: "ERROR", message: "You cannot access this Session." },
  },
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
