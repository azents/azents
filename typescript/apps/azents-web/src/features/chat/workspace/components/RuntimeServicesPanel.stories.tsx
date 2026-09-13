import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeServicesPanel } from "./RuntimeServicesPanel";
import type { RuntimeWebServiceResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const endpointId = "endpoint000000000000000000000000";
const requestId = "request0000000000000000000000000";
const cycleId = "cycle00000000000000000000000000";

function service(
  updates: Partial<RuntimeWebServiceResponse> = {},
): RuntimeWebServiceResponse {
  return {
    endpoint: {
      id: endpointId,
      port: 3000,
      label: "Preview app",
      url: "https://preview.services.example.com",
      configuration_state: "configured",
      authority_revision: 4,
      close_barrier: 0,
      created_at: "2026-09-12T00:00:00Z",
      updated_at: "2026-09-12T00:05:00Z",
    },
    current_request: null,
    current_cycle: null,
    active: false,
    duration_seconds: 3600,
    duration_configuration_revision: 2,
    observed_at: "2026-09-12T00:05:00Z",
    ...updates,
  };
}

const pendingRequest = {
  id: requestId,
  requester_kind: "agent" as const,
  state: "pending" as const,
  revision: 1,
  label: "Preview app",
  decided_by_user_id: null,
  decided_at: null,
  created_at: "2026-09-12T00:05:00Z",
  updated_at: "2026-09-12T00:05:00Z",
};

const activeCycle = {
  id: cycleId,
  request_id: requestId,
  duration_seconds: 3600,
  duration_configuration_revision: 2,
  approved_at: "2026-09-12T00:10:00Z",
  expires_at: "2026-09-12T01:10:00Z",
  close_barrier: 0,
  ended_at: null,
  end_reason: null,
};

const meta = {
  component: RuntimeServicesPanel,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: { type: "READY", services: [], runtimeAvailable: true },
    mutating: false,
    preparedService: null,
    mutationError: null,
    onPrepareService: fn(),
    onConfirmCreate: fn(),
    onResetPreparedService: fn(),
    onApprove: fn(),
    onReject: fn(),
    onCancel: fn(),
    onRequestAgain: fn(),
    onClose: fn(),
  },
} satisfies Meta<typeof RuntimeServicesPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty = {} satisfies Story;

export const Pending = {
  args: {
    state: {
      type: "READY",
      services: [service({ current_request: pendingRequest })],
      runtimeAvailable: true,
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Approve" }));
    const page = within(canvasElement.ownerDocument.body);
    await expect(
      page.getByRole("heading", { name: "Review web service access" }),
    ).toBeVisible();
    await userEvent.click(
      page.getByRole("button", { name: "Approve for 60 minutes" }),
    );
    await expect(args.onApprove).toHaveBeenCalled();
  },
} satisfies Story;

export const Active = {
  args: {
    state: {
      type: "READY",
      services: [service({ current_cycle: activeCycle, active: true })],
      runtimeAvailable: true,
    },
  },
} satisfies Story;

export const ActiveWithPendingRequest = {
  args: {
    state: {
      type: "READY",
      services: [
        service({
          current_request: pendingRequest,
          current_cycle: activeCycle,
          active: true,
        }),
      ],
      runtimeAvailable: true,
    },
  },
} satisfies Story;

export const Expired = {
  args: {
    state: {
      type: "READY",
      services: [
        service({
          current_cycle: {
            ...activeCycle,
            ended_at: "2026-09-12T01:10:00Z",
            end_reason: "expired",
          },
        }),
      ],
      runtimeAvailable: true,
    },
  },
} satisfies Story;

export const DisconnectedButApproved = {
  args: {
    state: {
      type: "READY",
      services: [service({ current_cycle: activeCycle, active: true })],
      runtimeAvailable: false,
    },
  },
} satisfies Story;

export const PermissionError = {
  args: {
    state: { type: "ERROR", message: "You cannot manage this Session." },
  },
} satisfies Story;

export const QuotaError = {
  args: {
    state: { type: "READY", services: [], runtimeAvailable: true },
    mutationError: "The active service quota is exhausted.",
  },
} satisfies Story;

export const Unconfigured = {
  args: {
    state: {
      type: "READY",
      services: [
        service({
          endpoint: {
            ...service().endpoint,
            url: null,
            configuration_state: "unconfigured",
          },
        }),
      ],
      runtimeAvailable: true,
    },
  },
} satisfies Story;

export const CreateConfirmation = {
  args: {
    preparedService: service(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Create service" }),
    );
    const page = within(canvasElement.ownerDocument.body);
    await expect(
      page.getByRole("heading", { name: "Expose this service?" }),
    ).toBeVisible();
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
  args: ActiveWithPendingRequest.args,
} satisfies Story;
