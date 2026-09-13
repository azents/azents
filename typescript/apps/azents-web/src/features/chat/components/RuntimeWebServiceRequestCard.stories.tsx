import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeWebServiceRequestCard } from "./RuntimeWebServiceRequestCard";
import type { RuntimeWebServiceResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const service: RuntimeWebServiceResponse = {
  endpoint: {
    id: "endpoint000000000000000000000000",
    port: 3000,
    label: "Preview app",
    url: "https://preview.services.example.com",
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
    label: "Preview app",
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
  component: RuntimeWebServiceRequestCard,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(620)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: {
      type: "READY",
      service,
      stale: false,
      action: null,
      actionError: null,
    },
    fallbackLabel: "Preview app",
    fallbackPort: 3000,
    fallbackUrl: "https://preview.services.example.com",
    onApprove: fn(),
    onReject: fn(),
    onCancel: fn(),
    onClose: fn(),
  },
} satisfies Meta<typeof RuntimeWebServiceRequestCard>;

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

export const StaleReadOnly = {
  args: {
    state: {
      type: "READY",
      service: { ...service, current_request: null },
      stale: true,
      action: null,
      actionError: null,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/stale/i)).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: /approve/i }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const ErrorState = {
  args: { state: { type: "ERROR", message: "Service unavailable" } },
} satisfies Story;
