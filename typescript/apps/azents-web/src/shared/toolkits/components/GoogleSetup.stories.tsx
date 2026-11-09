import { Modal } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import koreanMessages from "@/i18n/ko-KR-messages";
import { emptyGoogleMetadata } from "../google-editor";
import {
  googleFixtureScopes,
  googleGroupCatalog,
} from "../google-group-fixtures";
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
    subject: "account",
    email: "reader@example.invalid",
  },
  client_id: "client",
  ownership: "workspace_shared",
  reconnect_toolkit_id: "toolkit",
  services: ["calendar", "gmail"],
  tool_groups: ["calendar_read", "gmail_read"],
  oauth_request_scopes: googleFixtureScopes(["calendar", "gmail"]),
  granted_scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"],
  timeout: 30,
  accesses: [
    {
      service: "calendar",
      enabled: true,
      status: "partial",
      permitted_tools: ["calendar_list_events"],
      unavailable_tools: ["calendar_list_calendars"],
    },
    {
      service: "gmail",
      enabled: true,
      status: "not_granted",
      permitted_tools: [],
      unavailable_tools: ["gmail_search_messages"],
    },
  ],
  drive_access: noDrive,
  grant_result: "partial",
  renewable: true,
  can_confirm: true,
  service_access_verified: false,
};
const saved: GoogleConnectionOutput = {
  ...review,
  granted_tools: review.accesses.flatMap((access) => access.permitted_tools),
  toolkit_id: "toolkit",
  revision: 7,
  connection_id: "connection",
  status: "connected",
};
const props: GoogleSetupProps = {
  preparation: {
    type: "READY",
    detail: {
      status: "configured_unverified",
      client_id: "client",
      tool_group_catalog: googleGroupCatalog,
      callback_url: "https://app.example.invalid/oauth/google/callback",
      picker_status: "not_configured",
      service_access_verified: false,
    },
  },
  saved: { type: "NEW" },
  flow: { type: "SELECT" },
  services: [],
  toolGroups: [],
  timeout: 30,
  metadata: emptyGoogleMetadata,
  reconnect: false,
  ownership: "workspace",
  cancelling: false,
  disconnecting: false,
  savingServices: false,
  servicesDirty: false,
  settingsDirty: false,
  reviewDecision: null,
  picker: { type: "IDLE" },
  pickerAvailable: false,
  disconnectConfirmation: false,
  operationError: null,
  rootRef: { current: null },
  embedded: true,
  onServiceChange: fn(),
  onGroupChange: fn(),
  onPresetChange: fn(),
  onSaveServices: fn(() => Promise.resolve()),
  onApply: fn(),
  onReauthenticate: fn(),
  onClose: fn(),
  onRetryAuthorization: fn(() => Promise.resolve()),
  onOpenPicker: fn(),
  onClosePicker: fn(),
  onTimeoutChange: fn(),
  onMetadataChange: fn(),
  onAuthorize: fn(),
  onCheckOutcome: fn(() => Promise.resolve()),
  onCancel: fn(() => Promise.resolve()),
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
    const c = within(canvasElement);
    for (const service of ["Calendar", "Drive", "Gmail"]) {
      await expect(c.getByRole("switch", { name: service })).not.toBeChecked();
    }
    await expect(
      c.getByRole("button", { name: "Connect to Google" }),
    ).toBeDisabled();
    await expect(c.getByLabelText("Toolkit name")).not.toBeVisible();
    await userEvent.click(c.getByRole("switch", { name: "Drive" }));
    await expect(args.onServiceChange).toHaveBeenCalledWith("drive", true);
  },
};
export const SelectedServices: Story = {
  args: {
    services: ["calendar", "drive", "gmail"],
    toolGroups: ["calendar_read", "drive_read", "gmail_read"],
  },
  play: async ({ canvasElement, args }) => {
    const c = within(canvasElement);
    for (const service of ["Calendar", "Drive", "Gmail"]) {
      const presets = within(
        c.getByRole("group", { name: `${service} Permission preset` }),
      );
      const read = presets.getByRole("button", { name: "Read only" });
      await expect(read).toBeVisible();
      await userEvent.click(read);
      await expect(args.onPresetChange).toHaveBeenCalledWith(
        service.toLowerCase(),
        "read_only",
      );
    }
    await userEvent.click(c.getByRole("button", { name: "Connect to Google" }));
    await expect(args.onApply).toHaveBeenCalled();
    await expect(c.getByText("calendar_list_events")).not.toBeVisible();
    const permissions = c.getAllByText("Permissions and tools").at(0);
    if (permissions == null) {
      throw new Error("Calendar permissions are missing.");
    }
    await userEvent.click(permissions);
    await expect(
      c.getByRole("checkbox", { name: "Read calendars and events" }),
    ).toBeVisible();
  },
};
export const SavedEdit: Story = {
  args: {
    reconnect: true,
    saved: { type: "READY", detail: saved },
    services: saved.services,
    toolGroups: saved.tool_groups,
    metadata: { ...emptyGoogleMetadata, name: "Google", slug: "google" },
  },
  play: async ({ canvasElement, args }) => {
    const c = within(canvasElement);
    await expect(
      c.getByRole("button", { name: "Reauthenticate" }),
    ).toBeVisible();
    await expect(
      c.getByRole("button", { name: "Apply changes" }),
    ).toBeDisabled();
    await userEvent.click(c.getByRole("button", { name: "Reauthenticate" }));
    await expect(args.onReauthenticate).toHaveBeenCalled();
    await expect(
      c.queryByText("1. Prepare your connection"),
    ).not.toBeInTheDocument();
  },
};
function Editable(args: GoogleSetupProps): React.ReactElement {
  const [metadata, setMetadata] = useState(args.metadata);
  const [dirty, setDirty] = useState(false);
  return (
    <GoogleSetup
      {...args}
      rootRef={{ current: null }}
      metadata={metadata}
      settingsDirty={dirty}
      onMetadataChange={(patch) => {
        setMetadata((current) => ({ ...current, ...patch }));
        setDirty(true);
      }}
    />
  );
}
export const AdvancedEdit: Story = {
  args: SavedEdit.args,
  render: (args) => <Editable {...args} />,
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await userEvent.click(c.getByText("Advanced settings"));
    await userEvent.type(c.getByLabelText("Toolkit name"), " renamed");
    await expect(
      c.getByRole("button", { name: "Apply changes" }),
    ).toBeEnabled();
  },
};
export const PartialGrantReview: Story = {
  args: {
    ...SavedEdit.args,
    flow: { type: "REVIEW", review },
    reviewDecision: "PARTIAL",
  },
  play: async ({ canvasElement, args }) => {
    const c = within(canvasElement);
    await expect(
      c.getByRole("heading", { name: "Some permissions are missing" }),
    ).toBeVisible();
    await userEvent.click(c.getByRole("button", { name: "Reauthenticate" }));
    await expect(args.onRetryAuthorization).toHaveBeenCalled();
    await expect(c.getByRole("button", { name: "Cancel" })).toBeVisible();
  },
};
export const DifferentAccount: Story = {
  args: {
    ...PartialGrantReview.args,
    reviewDecision: "ACCOUNT",
    flow: {
      type: "REVIEW",
      review: {
        ...review,
        identity: {
          ...review.identity,
          subject: "new-account",
          email: "new@example.invalid",
        },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(
      c.getByText(
        "Google returned a different account. Reauthenticate with the saved account. Your existing connection has not changed.",
      ),
    ).toBeVisible();
    await expect(
      c.getByRole("button", { name: "Reauthenticate" }),
    ).toBeVisible();
  },
};
export const UnknownGrant: Story = {
  args: {
    ...PartialGrantReview.args,
    reviewDecision: "UNUSABLE",
    flow: {
      type: "REVIEW",
      review: { ...review, granted_scopes: null, can_confirm: false },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: "Reauthenticate",
      }),
    ).toBeEnabled();
  },
};
export const NoRenewal: Story = {
  args: {
    ...UnknownGrant.args,
    flow: {
      type: "REVIEW",
      review: { ...review, renewable: false, can_confirm: false },
    },
  },
};
export const UnknownPublication: Story = {
  args: {
    ...SavedEdit.args,
    flow: { type: "UNKNOWN", checking: false, message: null },
  },
  play: async ({ canvasElement, args }) => {
    const c = within(canvasElement);
    await userEvent.click(
      c.getByRole("button", { name: "Check saved result" }),
    );
    await expect(args.onCheckOutcome).toHaveBeenCalled();
    await expect(
      c.queryByRole("button", { name: "Apply changes" }),
    ).not.toBeInTheDocument();
  },
};
export const Complete: Story = {
  args: {
    ...SavedEdit.args,
    flow: {
      type: "COMPLETE",
      outcome: {
        toolkit_id: "toolkit",
        connection_id: "connection",
        current: true,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("status")).toHaveTextContent(
      "No additional save is needed",
    );
    await expect(
      c.getByRole("button", { name: "Apply changes" }),
    ).toBeDisabled();
  },
};
export const Loading: Story = {
  args: { preparation: { type: "LOADING" }, saved: { type: "LOADING" } },
};
export const StatusError: Story = {
  args: {
    saved: { type: "ERROR", message: "Unable to load the saved connection." },
  },
};
export const Verifying: Story = { args: { flow: { type: "VERIFYING" } } };
export const Failed: Story = {
  args: {
    flow: { type: "ERROR", message: "Authorization could not be verified." },
  },
};
export const MissingOperator: Story = {
  args: {
    preparation: {
      type: "READY",
      detail: {
        status: "not_configured",
        client_id: null,
        tool_group_catalog: googleGroupCatalog,
        callback_url: null,
        picker_status: "not_configured",
        service_access_verified: false,
      },
    },
  },
};
export const DisconnectConfirmation: Story = {
  args: { ...SavedEdit.args, disconnectConfirmation: true },
  play: async ({ canvasElement, args }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/does not revoke Google consent/)).toBeVisible();
    await userEvent.click(
      c.getByRole("button", { name: "Disconnect locally" }),
    );
    await expect(args.onDisconnect).toHaveBeenCalled();
  },
};
export const PickerOpen: Story = {
  args: {
    ...SavedEdit.args,
    services: ["drive"],
    saved: {
      type: "READY",
      detail: {
        ...saved,
        services: ["drive"],
        drive_access: {
          ...noDrive,
          whole_content_read: true,
          app_file_write: true,
        },
      },
    },
    picker: { type: "OPEN" },
    pickerAvailable: true,
  },
  play: async ({ canvasElement, args }) => {
    const c = within(canvasElement);
    const permissions = c.getAllByText("Permissions and tools").at(1);
    if (permissions == null) {
      throw new Error("Drive permissions are missing.");
    }
    await userEvent.click(permissions);
    const button = c.getByRole("button", { name: "Close file chooser" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onClosePicker).toHaveBeenCalled();
  },
};
export const KoreanSavedModal: Story = {
  args: SavedEdit.args,
  render: (args) => (
    <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
      <Modal opened onClose={() => {}} size="lg" centered title="Google">
        <GoogleSetup {...args} rootRef={{ current: null }} />
      </Modal>
    </NextIntlClientProvider>
  ),
};
export const KoreanNewModal: Story = {
  ...KoreanSavedModal,
  args: SelectedServices.args,
};
export const KoreanPartialReview: Story = {
  ...KoreanSavedModal,
  args: PartialGrantReview.args,
};
export const MobileSavedModal: Story = {
  ...KoreanSavedModal,
  globals: { viewport: { value: "mobile1", isRotated: false } },
  play: async ({ canvasElement }) => {
    const body = within(canvasElement.ownerDocument.body),
      dialog = body.getByRole("dialog");
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(
      dialog.clientWidth + 1,
    );
    await expect(body.getByRole("button", { name: "재인증" })).toBeVisible();
  },
};
export const PickerModalScroll: Story = {
  args: { ...PickerOpen.args, picker: { type: "IDLE" } },
  render: (args) => (
    <Modal opened onClose={() => {}} size="lg" centered title="Google">
      <GoogleSetup {...args} rootRef={{ current: null }} />
    </Modal>
  ),
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    const permissions = body.getAllByText("Permissions and tools").at(1);
    if (permissions == null) {
      throw new Error("Drive permissions are missing.");
    }
    await userEvent.click(permissions);
    const button = body.getByRole("button", {
      name: "Choose Drive files with Google",
    });
    button.scrollIntoView({ block: "end" });
    const rect = button.getBoundingClientRect();
    const hit = button.ownerDocument.elementFromPoint(
      rect.x + rect.width / 2,
      rect.y + rect.height / 2,
    );
    await expect(button.contains(hit)).toBe(true);
    await userEvent.click(button);
    await expect(args.onOpenPicker).toHaveBeenCalledOnce();
  },
};
