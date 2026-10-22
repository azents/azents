import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import koreanMessages from "@/i18n/ko-KR-messages";
import { googleScopesForServices } from "../google-access";
import { canPublishGoogleReview } from "../google-types";
import { GoogleSetup } from "./GoogleSetup";
import type { GoogleSetupProps } from "../google-types";
import type {
  GoogleConnectionOutput,
  GoogleReview,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noDrive = {
  whole_metadata_read: false,
  whole_content_read: false,
  whole_content_write: false,
  whole_metadata_write: false,
  app_file_read: false,
  app_file_write: false,
};
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
  services: ["calendar", "gmail"],
  oauth_request_scopes: googleScopesForServices(["calendar", "gmail"]),
  granted_scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"],
  timeout: 30,
  accesses: [
    {
      service: "calendar",
      enabled: true,
      status: "partial",
      permitted_tools: ["calendar_list_events"],
      unavailable_tools: ["calendar_create_event"],
    },
    {
      service: "gmail",
      enabled: true,
      status: "not_granted",
      permitted_tools: [],
      unavailable_tools: ["gmail_search_messages"],
    },
    {
      service: "drive",
      enabled: false,
      status: "disabled",
      permitted_tools: [],
      unavailable_tools: ["drive_search_files"],
    },
  ],
  drive_access: noDrive,
  grant_result: "partial",
  renewable: true,
  can_confirm: true,
  service_access_verified: false,
};
const saved: GoogleConnectionOutput = {
  toolkit_id: "toolkit",
  revision: 7,
  connection_id: "connection",
  status: "connected",
  identity: review.identity,
  services: review.services,
  oauth_request_scopes: review.oauth_request_scopes,
  granted_scopes: review.granted_scopes,
  timeout: 30,
  accesses: review.accesses,
  drive_access: noDrive,
  renewable: true,
  service_access_verified: false,
};
const props: GoogleSetupProps = {
  preparation: {
    type: "READY",
    detail: {
      status: "configured_unverified",
      client_id: "client",
      callback_url: "https://app.example.invalid/oauth/google/callback",
      picker_status: "not_configured",
      service_access_verified: false,
    },
  },
  saved: { type: "NEW" },
  flow: { type: "SELECT" },
  services: [],
  timeout: 30,
  metadata: {
    name: "",
    slug: "",
    description: "",
    prompt: "",
    enabled: true,
    alwaysExposeTools: false,
  },
  publishingAllowed: false,
  reconnect: false,
  ownership: "workspace",
  cancelling: false,
  disconnecting: false,
  savingServices: false,
  servicesDirty: false,
  picker: { type: "IDLE" },
  pickerAvailable: false,
  disconnectConfirmation: false,
  operationError: null,
  rootRef: { current: null },
  embedded: false,
  onServiceChange: fn(),
  onSaveServices: fn(() => Promise.resolve()),
  onOpenPicker: fn(),
  onClosePicker: fn(),
  onTimeoutChange: fn(),
  onMetadataChange: fn(),
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
  tags: ["ci-contract"],
  args: props,
  render: (args) => <GoogleSetup {...args} rootRef={{ current: null }} />,
} satisfies Meta<typeof GoogleSetup>;
export default meta;
type Story = StoryObj<typeof meta>;
export const ExplicitSelection: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    for (const toggle of canvas.getAllByRole("switch")) {
      await expect(toggle).not.toBeChecked();
    }
    await expect(
      canvas.getByRole("button", { name: "Continue to Google" }),
    ).toBeDisabled();
    await userEvent.click(canvas.getByRole("switch", { name: "Drive" }));
    await expect(args.onServiceChange).toHaveBeenCalledWith("drive", true);
  },
};
export const SelectedServices: Story = {
  args: { services: ["drive"] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("switch", { name: "Drive" })).toBeChecked();
    await userEvent.click(
      canvas.getByRole("button", { name: "Continue to Google" }),
    );
    await expect(args.onAuthorize).toHaveBeenCalled();
  },
};
function ReviewFixture(args: GoogleSetupProps): React.ReactElement {
  const [services, setServices] = useState(args.services);
  const current = args.flow.type === "REVIEW" ? args.flow.review : review;
  return (
    <GoogleSetup
      {...args}
      rootRef={{ current: null }}
      services={services}
      publishingAllowed={canPublishGoogleReview(current, services, Date.now())}
      onServiceChange={(service, selected) =>
        setServices((previous) =>
          selected
            ? [...previous, service]
            : previous.filter((item) => item !== service),
        )
      }
    />
  );
}
export const PartialGrantReview: Story = {
  args: {
    flow: { type: "REVIEW", review },
    services: ["calendar", "gmail"],
  },
  render: (args) => <ReviewFixture {...args} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Partially permitted", { exact: true }),
    ).toBeVisible();
    await expect(
      canvas.getByText("Not granted", { exact: true }),
    ).toBeVisible();
    const save = canvas.getByRole("button", { name: "Save Google Toolkit" });
    await expect(save).toBeEnabled();
    await userEvent.click(save);
    await expect(args.onPublish).toHaveBeenCalled();
  },
};
export const PersonalReview: Story = {
  ...PartialGrantReview,
  args: {
    ...PartialGrantReview.args,
    ownership: "user",
    flow: { type: "REVIEW", review: { ...review, ownership: "personal" } },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(
        /Only your personal Sessions with allowed Agents/,
      ),
    ).toBeVisible();
  },
};
export const UnknownGrant: Story = {
  args: {
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        grant_result: "unknown",
        granted_scopes: null,
        can_confirm: false,
        accesses: review.accesses.map((access) => ({
          ...access,
          status: "unknown",
          permitted_tools: [],
        })),
      },
    },
    services: ["calendar"],
  },
};
export const NoRenewal: Story = {
  args: {
    flow: {
      type: "REVIEW",
      review: { ...review, renewable: false, can_confirm: false },
    },
    services: ["calendar"],
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
        status: "not_configured",
        client_id: null,
        callback_url: null,
        picker_status: "not_configured",
        service_access_verified: false,
      },
    },
  },
};
export const Loading: Story = {
  args: { preparation: { type: "LOADING" }, saved: { type: "LOADING" } },
};
export const StatusError: Story = {
  args: {
    saved: { type: "ERROR", message: "Unable to load this saved connection." },
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
    await userEvent.click(
      canvas.getByRole("button", { name: "Check saved result" }),
    );
    await expect(args.onCheckOutcome).toHaveBeenCalled();
  },
};
export const SavedReconnectRequired: Story = {
  args: {
    reconnect: true,
    services: saved.services,
    saved: {
      type: "READY",
      detail: { ...saved, status: "reconnect_required" },
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
export const AllServicesOff: Story = {
  args: {
    reconnect: true,
    saved: {
      type: "READY",
      detail: {
        ...saved,
        services: [],
        accesses: saved.accesses.map((access) => ({
          ...access,
          enabled: false,
          status: "disabled",
          permitted_tools: [],
        })),
      },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(
        /saved account and grant remain connected/,
      ),
    ).toBeVisible();
  },
};
export const LocalServiceChanges: Story = {
  args: { ...SavedReconnectRequired.args, services: [], servicesDirty: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const save = canvas.getByRole("button", { name: "Save service switches" });
    await expect(save).toBeEnabled();
    await userEvent.click(save);
    await expect(args.onSaveServices).toHaveBeenCalled();
    await expect(
      canvas.getByRole("button", { name: "Authorize replacement connection" }),
    ).toBeDisabled();
  },
};
export const SavingServices: Story = {
  args: { ...LocalServiceChanges.args, savingServices: true },
};
export const ServiceSaveError: Story = {
  args: {
    ...LocalServiceChanges.args,
    operationError:
      "Service settings changed. Review the refreshed connection.",
  },
};
const mixedDrive = {
  ...noDrive,
  whole_content_read: true,
  whole_metadata_read: true,
  app_file_read: true,
  app_file_write: true,
};
export const MixedDriveGrant: Story = {
  args: {
    ...SavedReconnectRequired.args,
    services: ["drive"],
    saved: {
      type: "READY",
      detail: { ...saved, services: ["drive"], drive_access: mixedDrive },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Read content across Drive.")).toBeVisible();
    await expect(canvas.getByText(/Write only app-created/)).toBeVisible();
  },
};
export const PickerLoading: Story = {
  args: {
    ...MixedDriveGrant.args,
    picker: { type: "LOADING" },
    pickerAvailable: true,
  },
};
export const PickerOpen: Story = {
  args: {
    ...MixedDriveGrant.args,
    picker: { type: "OPEN" },
    pickerAvailable: true,
  },
  play: async ({ canvasElement, args }) => {
    const close = within(canvasElement).getByRole("button", {
      name: "Close file chooser",
    });
    close.focus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onClosePicker).toHaveBeenCalled();
  },
};
export const PickerSelection: Story = {
  args: { ...MixedDriveGrant.args, picker: { type: "SELECTED", count: 2 } },
};
export const PickerCancelled: Story = {
  args: { ...MixedDriveGrant.args, picker: { type: "CANCELLED" } },
};
export const PickerError: Story = {
  args: {
    ...MixedDriveGrant.args,
    picker: {
      type: "ERROR",
      message: "The temporary file-selection credential expired.",
    },
  },
};
export const MobilePartialReview: Story = {
  ...PartialGrantReview,
  globals: { viewport: { value: "mobile1", isRotated: false } },
};
export const NoGrantedServices: Story = {
  args: {
    ...UnknownGrant.args,
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        can_confirm: false,
        grant_result: "none",
        accesses: review.accesses.map((access) => ({
          ...access,
          permitted_tools: [],
          status: "not_granted",
        })),
      },
    },
  },
};
export const FullGrantReview: Story = {
  args: {
    ...PartialGrantReview.args,
    services: ["calendar"],
    publishingAllowed: true,
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        services: ["calendar"],
        grant_result: "full",
        oauth_request_scopes: googleScopesForServices(["calendar"]),
        granted_scopes: googleScopesForServices(["calendar"]),
      },
    },
  },
};
export const KoreanPartialReview: Story = {
  args: PartialGrantReview.args,
  render: (args) => (
    <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
      <GoogleSetup {...args} rootRef={{ current: null }} />
    </NextIntlClientProvider>
  ),
};

export const BroaderScopeReceipt: Story = {
  args: {
    ...PartialGrantReview.args,
    services: ["gmail"],
    publishingAllowed: true,
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        services: ["gmail"],
        oauth_request_scopes: [
          "https://www.googleapis.com/auth/gmail.readonly",
        ],
        granted_scopes: ["https://www.googleapis.com/auth/gmail.modify"],
        accesses: [
          {
            service: "gmail",
            enabled: true,
            status: "partial",
            permitted_tools: ["gmail_get_message", "gmail_send_message"],
            unavailable_tools: ["gmail_create_filter"],
          },
        ],
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Google returned different scope values"),
    ).toBeVisible();
    await userEvent.click(canvas.getByText("Inspect exact tool permissions"));
    await expect(
      canvas.getByText("gmail_get_message", { exact: true }),
    ).toBeVisible();
    await expect(
      canvas.getByText("gmail_send_message", { exact: true }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Save Google Toolkit" }),
    ).toBeEnabled();
  },
};
