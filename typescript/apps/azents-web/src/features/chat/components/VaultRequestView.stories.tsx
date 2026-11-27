import { fn } from "storybook/test";
import { VaultRequestCard, VaultRequestDialog } from "./VaultRequestView";
import type { VaultRequestView } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const request: VaultRequestView = {
  request_id: "a".repeat(32),
  purpose: "Connect the example reporting account.",
  fields: [
    { name: "reporting-account", label: "Account" },
    { name: "reporting-password", label: "Password" },
  ],
  status: "open",
  deadline_at: "2026-11-29T02:00:00Z",
  can_submit: true,
};

const meta = {
  component: VaultRequestCard,
  args: { request, loading: false, onOpen: fn() },
} satisfies Meta<typeof VaultRequestCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Open: Story = {};
export const Submitted: Story = {
  args: { request: { ...request, status: "submitted", can_submit: false } },
};
export const Expired: Story = {
  args: { request: { ...request, status: "expired", can_submit: false } },
};
export const Unavailable: Story = { args: { request: null } };
export const EntryDialog: Story = {
  render: () => (
    <VaultRequestDialog
      agentName="Reporting Agent"
      request={request}
      loading={false}
      values={new Map()}
      busy={false}
      failed={false}
      onClose={fn()}
      onFieldChange={fn()}
      onSubmit={(event) => event.preventDefault()}
    />
  ),
};
