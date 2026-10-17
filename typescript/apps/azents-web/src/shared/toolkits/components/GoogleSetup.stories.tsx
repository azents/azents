import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import koreanMessages from "@/i18n/ko-KR-messages";
import { canPublishGoogleReview } from "../google-types";
import { GoogleSetup } from "./GoogleSetup";
import type { GoogleSetupProps } from "../google-types";
import type { GoogleReview } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const review: GoogleReview = {
  attempt_id: "candidate",
  expires_at: "2030-01-01T00:00:00Z",
  identity: {
    issuer: "https://accounts.google.com",
    subject: "test-account",
    email: "reader@example.invalid",
  },
  client_id: "test-client",
  ownership: "workspace_shared",
  reconnect_toolkit_id: null,
  requested_tasks: ["calendar_read", "gmail_read"],
  timeout: 30,
  tasks: [
    {
      task: "calendar_read",
      service: "calendar",
      status: "partial",
      permitted_tools: ["list_events"],
      unavailable_tools: ["list_calendars"],
    },
    {
      task: "gmail_read",
      service: "gmail",
      status: "not_granted",
      permitted_tools: [],
      unavailable_tools: ["list_messages"],
    },
  ],
  grant_result: "partial",
  renewable: true,
  can_confirm: true,
  service_access_verified: false,
  security_notice: "Known-pattern screening is incomplete.",
};
const props: GoogleSetupProps = {
  preparation: {
    type: "READY",
    detail: {
      status: "configured_unverified",
      client_id: "client",
      callback_url: "https://app.example.invalid/oauth/google/callback",
      preview_verified: false,
      service_access_verified: false,
    },
  },
  saved: { type: "NEW" },
  flow: { type: "SELECT" },
  tasks: [],
  timeout: 30,
  metadata: {
    name: "",
    slug: "",
    description: "",
    prompt: "",
    enabled: true,
    alwaysExposeTools: false,
  },
  acknowledged: false,
  publishingAllowed: false,
  reconnect: false,
  ownership: "workspace",
  cancelling: false,
  disconnecting: false,
  disconnectConfirmation: false,
  operationError: null,
  rootRef: { current: null },
  embedded: false,
  onTaskChange: fn(),
  onTimeoutChange: fn(),
  onMetadataChange: fn(),
  onAcknowledgedChange: fn(),
  onAuthorize: fn(),
  onPublish: fn(),
  onCheckOutcome: fn(),
  onCancel: fn(),
  onRestart: fn(),
  onRefresh: fn(),
  onAskDisconnect: fn(),
  onDismissDisconnect: fn(),
  onDisconnect: fn(),
};
const meta = {
  title: "Toolkits/Google Connection",
  component: GoogleSetup,
  args: props,
} satisfies Meta<typeof GoogleSetup>;
export default meta;
type Story = StoryObj<typeof meta>;
export const ExplicitSelection: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const checkbox of canvas.getAllByRole("checkbox")) {
      await expect(checkbox).not.toBeChecked();
    }
    await expect(
      canvas.getByRole("button", { name: "Continue to Google" }),
    ).toBeDisabled();
  },
};
export const SelectedTasks: Story = {
  args: { tasks: ["calendar_read"] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Continue to Google" }),
    );
    await expect(args.onAuthorize).toHaveBeenCalled();
    await expect(
      canvas.getAllByText("Sending mail is not included.", { exact: false }),
    ).toHaveLength(2);
  },
};
export const PersonalReview: Story = {
  args: {
    ownership: "user",
    flow: { type: "REVIEW", review: { ...review, ownership: "personal" } },
    tasks: ["calendar_read"],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(
        "This connection belongs to your account. Only your personal Sessions with allowed Agents can use it.",
      ),
    ).toBeVisible();
    await expect(
      canvas.queryByText(
        "Workspace-shared connection: authorized users and Agents may act using this saved account.",
      ),
    ).not.toBeInTheDocument();
  },
};
function AcknowledgementFixture(args: GoogleSetupProps): React.ReactElement {
  const [acknowledged, setAcknowledged] = useState(false);
  return (
    <GoogleSetup
      {...args}
      acknowledged={acknowledged}
      publishingAllowed={canPublishGoogleReview(
        review,
        args.tasks,
        acknowledged,
        Date.now(),
      )}
      onAcknowledgedChange={setAcknowledged}
    />
  );
}
export const PartialGrantReview: Story = {
  args: {
    flow: { type: "REVIEW", review },
    tasks: ["calendar_read", "gmail_read"],
  },
  render: (args) => <AcknowledgementFixture {...args} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Partially permitted", { exact: true }),
    ).toBeVisible();
    await expect(
      canvas.getByText("Not granted", { exact: true }),
    ).toBeVisible();
    const save = canvas.getByRole("button", { name: "Save Google Toolkit" });
    await expect(save).toBeDisabled();
    await userEvent.click(
      canvas.getByRole("checkbox", {
        name: "I have reviewed these screening limits and the ownership of this connection.",
      }),
    );
    await expect(save).toBeEnabled();
    await userEvent.click(save);
    await expect(args.onPublish).toHaveBeenCalled();
  },
};
export const UnknownGrant: Story = {
  args: {
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        grant_result: "unknown",
        can_confirm: false,
        tasks: review.tasks.map((task) => ({
          ...task,
          status: "unknown",
          permitted_tools: [],
        })),
      },
    },
    tasks: ["calendar_read"],
    acknowledged: true,
  },
};
export const NoRenewal: Story = {
  args: {
    flow: {
      type: "REVIEW",
      review: { ...review, renewable: false, can_confirm: false },
    },
    tasks: ["calendar_read"],
    acknowledged: true,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Save Google Toolkit" }),
    ).toBeDisabled();
    await expect(
      canvas.getByText(/No renewable credential was returned/),
    ).toBeVisible();
  },
};
export const MissingOperator: Story = {
  args: {
    preparation: {
      type: "READY",
      detail: {
        ...(props.preparation.type === "READY"
          ? props.preparation.detail
          : {
              client_id: null,
              callback_url: null,
              preview_verified: false,
              service_access_verified: false,
            }),
        status: "not_configured",
      },
    },
  },
};
export const Verifying: Story = { args: { flow: { type: "VERIFYING" } } };
export const Failed: Story = {
  args: {
    flow: { type: "ERROR", message: "Authorization could not be verified." },
  },
};
export const UnknownPublication: Story = {
  args: { flow: { type: "UNKNOWN", checking: false, message: null } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("button", { name: "Save Google Toolkit" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", { name: "Check saved result" }),
    );
    await expect(args.onCheckOutcome).toHaveBeenCalled();
  },
};
export const SavedReconnectRequired: Story = {
  args: {
    reconnect: true,
    tasks: ["calendar_read"],
    saved: {
      type: "READY",
      detail: {
        toolkit_id: "toolkit",
        status: "reconnect_required",
        identity: review.identity,
        selected_tasks: ["calendar_read"],
        timeout: 30,
        tasks: review.tasks,
        renewable: true,
        service_access_verified: false,
      },
    },
  },
};
export const DisconnectConfirmation: Story = {
  args: { ...SavedReconnectRequired.args, disconnectConfirmation: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(/does not revoke Google consent/),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Disconnect locally" }),
    );
    await expect(args.onDisconnect).toHaveBeenCalled();
  },
};
export const MobilePartialReview: Story = {
  ...PartialGrantReview,
  globals: { viewport: { value: "mobile1", isRotated: false } },
};
export const NoGrantedTasks: Story = {
  args: {
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        grant_result: "none",
        can_confirm: false,
        tasks: review.tasks.map((access) => ({
          ...access,
          status: "not_granted",
          permitted_tools: [],
        })),
      },
    },
    tasks: ["calendar_read", "gmail_read"],
    acknowledged: true,
  },
};
export const FullGrantReview: Story = {
  args: {
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        grant_result: "full",
        requested_tasks: ["calendar_read"],
        tasks: [
          {
            task: "calendar_read",
            service: "calendar",
            status: "permitted",
            permitted_tools: [
              "list_events",
              "get_event",
              "search_events",
              "list_calendars",
            ],
            unavailable_tools: [],
          },
        ],
      },
    },
    tasks: ["calendar_read"],
  },
};
export const KoreanPartialReview: Story = {
  args: {
    flow: { type: "REVIEW", review },
    tasks: ["calendar_read", "gmail_read"],
  },
  render: (args) => (
    <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
      <GoogleSetup {...args} />
    </NextIntlClientProvider>
  ),
};
