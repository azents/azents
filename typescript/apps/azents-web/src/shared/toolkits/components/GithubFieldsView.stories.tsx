import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { GithubFieldsView } from "./GithubFieldsView";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: GithubFieldsView,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(680)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    config: {
      github_auth_type: "pat",
      toolsets: ["repos"],
      inject_runtime_environment: false,
    },
    credentials: { type: "pat" },
    hasCredentials: false,
    savedUserRegistration: false,
    authorizationState: null,
    availability: {
      type: "READY",
      availability: {
        platform: "configured",
        callback_url: "https://azents.example/oauth/github/callback",
      },
    },
    selectedInstallations: [],
    installationState: { type: "IDLE", installations: [] },
    testState: { type: "IDLE" },
    runtimeAcknowledged: false,
    canTest: true,
    onRetryAvailability: fn(),
    onConfigChange: fn(),
    onCredentialsChange: fn(),
    onConnectInstallations: fn(),
    onInstallApp: fn(),
    onTest: fn(),
    onRuntimeAcknowledged: fn(),
  },
} satisfies Meta<typeof GithubFieldsView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const PatDefault = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Authentication Method")).toHaveValue(
      "Personal Access Token",
    );
  },
} satisfies Story;
export const FiveAuthenticationChoices = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByLabelText("Authentication Method"));
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getAllByRole("option")).toHaveLength(5);
  },
} satisfies Story;
export const PlatformAbsent = {
  args: {
    availability: {
      type: "READY",
      availability: {
        platform: "absent",
        callback_url: "https://azents.example/oauth/github/callback",
      },
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByLabelText("Authentication Method"),
    );
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getAllByRole("option")).toHaveLength(3);
    await expect(
      page.getByRole("option", {
        name: "GitHub App (self-managed) · user account",
      }),
    ).toBeVisible();
  },
} satisfies Story;
export const PlatformIncomplete = {
  args: {
    availability: {
      type: "READY",
      availability: {
        platform: "incomplete",
        callback_url: "https://azents.example/oauth/github/callback",
      },
    },
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByLabelText("Authentication Method"),
    );
    await expect(
      within(canvasElement.ownerDocument.body).getAllByRole("option"),
    ).toHaveLength(5);
  },
} satisfies Story;
export const AvailabilityLoading = {
  args: { availability: { type: "LOADING" } },
} satisfies Story;
export const AvailabilityErrorNotAbsence = {
  args: { availability: { type: "ERROR" } },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByLabelText("Authentication Method"),
    );
    await expect(
      within(canvasElement.ownerDocument.body).getAllByRole("option"),
    ).toHaveLength(5);
  },
} satisfies Story;
export const SavedMissingPlatform = {
  args: {
    config: { github_auth_type: "github_app_platform_user" },
    credentials: { type: "github_app_platform_user" },
    hasCredentials: true,
    canTest: false,
    availability: {
      type: "READY",
      availability: {
        platform: "absent",
        callback_url: "https://azents.example/oauth/github/callback",
      },
    },
  },
} satisfies Story;
export const NewByoaUser = {
  args: {
    config: { github_auth_type: "github_app_user" },
    credentials: { type: "github_app_user" },
    canTest: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByLabelText("OAuth Client ID", { exact: false }),
    ).toBeRequired();
    await expect(
      canvas.getByLabelText("OAuth Client Secret", { exact: false }),
    ).toBeRequired();
    await expect(
      canvas.queryByRole("button", { name: "Add installation" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;
export const RedactedByoaEdit = {
  args: {
    ...NewByoaUser.args,
    hasCredentials: true,
    savedUserRegistration: true,
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByLabelText("OAuth Client ID", { exact: false }),
    ).not.toBeRequired();
    await expect(
      canvas.getByLabelText("OAuth Client ID", { exact: false }),
    ).toHaveValue("");
    await userEvent.type(
      canvas.getByLabelText("OAuth Client Secret", { exact: false }),
      "replacement",
    );
    await expect(args.onCredentialsChange).toHaveBeenCalled();
  },
} satisfies Story;
export const ByoaInstallationUnchanged = {
  args: {
    config: { github_auth_type: "github_app" },
    credentials: { type: "github_app" },
    canTest: true,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByLabelText("OAuth Client ID"),
    ).not.toBeInTheDocument();
    await expect(
      canvas.getByRole("button", { name: "Add installation" }),
    ).toBeVisible();
  },
} satisfies Story;
export const PlatformInstallations = {
  args: {
    config: { github_auth_type: "github_app_platform" },
    installationState: {
      type: "READY",
      installations: [
        {
          id: 10,
          account_login: "personal",
          account_type: "User",
          account_avatar_url: "",
        },
        {
          id: 20,
          account_login: "org",
          account_type: "Organization",
          account_avatar_url: "",
        },
      ],
    },
    selectedInstallations: [
      {
        installation_id: "10",
        account_login: "personal",
        account_type: "User",
        account_avatar_url: null,
      },
    ],
  },
} satisfies Story;
