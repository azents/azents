import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { DEFAULT_GITHUB_WIZARD_SETTINGS } from "../github-wizard-state";
import {
  wizardCandidateConnection,
  wizardReviewProps,
  wizardStoryProps,
} from "./github-wizard-story-fixtures";
import { GitHubWizard } from "./GitHubWizard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/GitHub Wizard",
  component: GitHubWizard,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: wizardStoryProps,
} satisfies Meta<typeof GitHubWizard>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Identity: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", {
        name: "How would you like to connect to GitHub?",
      }),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "Save GitHub connection" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", { name: /Connect with my GitHub account/ }),
    );
    await expect(args.onIdentity).toHaveBeenCalledWith("PERSONAL");
  },
};
export const PersonalMethods: Story = {
  args: { identity: "PERSONAL" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "GitHub App · Azents Test App" }),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Register a GitHub App" }),
    );
    await expect(args.onMode).toHaveBeenCalledWith("github_app_user");
  },
};
export const AppMethods: Story = {
  args: { identity: "APP" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("button", { name: "Personal access token (PAT)" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", { name: "Register a GitHub App" }),
    );
    await expect(args.onMode).toHaveBeenCalledWith("github_app");
  },
};
export const PlatformAbsent: Story = {
  args: {
    identity: "PERSONAL",
    availability: {
      type: "READY",
      userAccount: "absent",
      installation: "absent",
      callbackUrl: null,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("button", { name: /GitHub App ·/ }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.getByRole("button", { name: "Personal access token (PAT)" }),
    ).toBeVisible();
  },
};
export const PerIdentityReadiness: Story = {
  args: {
    identity: "APP",
    availability: {
      type: "READY",
      userAccount: "incomplete",
      installation: "configured",
      callbackUrl: null,
    },
  },
};
export const PlatformIncomplete: Story = {
  args: {
    identity: "PERSONAL",
    availability: {
      type: "READY",
      userAccount: "incomplete",
      installation: "configured",
      callbackUrl: null,
    },
  },
};
export const AvailabilityLoading: Story = {
  args: { identity: "PERSONAL", availability: { type: "LOADING" } },
};
export const AvailabilityError: Story = {
  args: { identity: "PERSONAL", availability: { type: "ERROR" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Retry" }));
    await expect(args.onRetryAvailability).toHaveBeenCalledOnce();
    await expect(
      canvas.getByRole("button", { name: "Register a GitHub App" }),
    ).toBeVisible();
  },
};
export const MetadataLoading: Story = {
  args: { identity: "PERSONAL", platformApp: { type: "LOADING" } },
};
export const MetadataError: Story = {
  args: {
    identity: "PERSONAL",
    platformApp: {
      type: "ERROR",
      message:
        "GitHub App information could not be loaded. Retry to use this method.",
    },
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Retry" }),
    );
    await expect(args.onRetryPlatformMetadata).toHaveBeenCalledOnce();
  },
};
export const PatInput: Story = {
  args: { identity: "PERSONAL", mode: "pat" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText(/OAuth callback/)).not.toBeInTheDocument();
    await expect(
      canvas.getByRole("button", { name: "Continue to features" }),
    ).toBeDisabled();
  },
};
export const SelfManagedUserInput: Story = {
  args: { identity: "PERSONAL", mode: "github_app_user" },
};
export const SelfManagedAppInput: Story = {
  args: { identity: "APP", mode: "github_app" },
};
export const PlatformInstallations: Story = {
  args: {
    identity: "APP",
    mode: "github_app_platform",
    installationState: {
      type: "READY",
      installations: [
        { id: 7, account_login: "fixture-org", account_type: "Organization" },
      ],
    },
  },
};
export const VerifyingCloseAllowed: Story = {
  args: { identity: "PERSONAL", mode: "pat", connection: { type: "LOADING" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Close" }));
    await expect(args.onClose).toHaveBeenCalledOnce();
    await expect(
      canvas.getByRole("button", { name: "Reset connection" }),
    ).toBeEnabled();
  },
};
export const ConnectionError: Story = {
  args: {
    identity: "APP",
    mode: "github_app",
    connection: {
      type: "ERROR",
      message: "The connection could not be verified.",
    },
  },
};
export const CandidateInline: Story = {
  args: {
    identity: "PERSONAL",
    mode: "github_app_user",
    connection: wizardCandidateConnection,
    canContinue: true,
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("fixture-user")).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "Save GitHub connection" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", { name: "Continue to features" }),
    );
    await expect(args.onContinue).toHaveBeenCalledOnce();
    await expect(args.onPublish).not.toHaveBeenCalled();
    await expect(canvas.getByRole("button", { name: "Close" })).toBeEnabled();
  },
};
export const CandidateMetadataError: Story = {
  args: {
    identity: "PERSONAL",
    mode: "github_app_user",
    connection: {
      ...wizardCandidateConnection,
      app: { type: "ERROR", message: "App information could not be loaded." },
    },
    canContinue: false,
  },
};
export const Features: Story = {
  args: { ...wizardReviewProps, stage: "FEATURES" },
};
export const RuntimeOff: Story = {
  args: { ...wizardReviewProps, stage: "RUNTIME" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("checkbox")).not.toBeInTheDocument();
    await expect(
      canvas.getByRole("button", { name: "Review connection" }),
    ).toBeEnabled();
  },
};
export const RuntimeRiskUnacknowledged: Story = {
  args: {
    ...wizardReviewProps,
    stage: "RUNTIME",
    settings: {
      ...DEFAULT_GITHUB_WIZARD_SETTINGS,
      injectRuntimeEnvironment: true,
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Review connection" }),
    ).toBeDisabled();
    await userEvent.click(canvas.getByRole("checkbox"));
    await expect(args.onSettings).toHaveBeenCalledWith({
      ...args.settings,
      runtimeRiskAcknowledged: true,
    });
  },
};
export const FinalReview: Story = {
  args: wizardReviewProps,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Development GitHub",
    );
    await expect(
      canvas.getByText(
        "Workspace-shared Toolkit: attached Agents and their authorized participants perform ordinary and automatic GitHub work with the verified identity, not each participant's own account.",
      ),
    ).toBeVisible();
    await expect(
      canvas.queryByText(/Agent-only Toolkit:/),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: /Cancel/ }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("textbox", { name: "Slug" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", { name: "Advanced settings" }),
    );
    await expect(canvas.getByRole("textbox", { name: "Slug" })).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Save GitHub connection" }),
    );
    await expect(args.onPublish).toHaveBeenCalledOnce();
  },
};
export const AgentReview: Story = {
  args: { ...wizardReviewProps, embedded: true, sharingScope: "agent_only" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(
        "Agent-only Toolkit: only this Agent and its authorized participants perform ordinary and automatic GitHub work with the verified identity, not each participant's own account.",
      ),
    ).toBeVisible();
    await expect(
      canvas.queryByText(/Workspace-shared Toolkit:/),
    ).not.toBeInTheDocument();
  },
};
export const PublicationPending: Story = {
  args: {
    ...wizardReviewProps,
    publication: { type: "PENDING" },
    onClose: fn(),
    onReset: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Close" })).toBeDisabled();
    await expect(
      canvas.getByRole("button", { name: "Reset connection" }),
    ).toBeDisabled();
    await userEvent.click(
      canvas.getByRole("button", { name: "Reset connection" }),
    );
    await expect(args.onReset).not.toHaveBeenCalled();
  },
};
export const PublicationFailed: Story = {
  args: {
    ...wizardReviewProps,
    publication: {
      type: "ERROR",
      message:
        "The connection was not saved. Review settings, then explicitly save again.",
    },
  },
};
export const UncertainPublication: Story = {
  args: { ...wizardReviewProps, publication: { type: "UNCERTAIN" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Save GitHub connection" }),
    ).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Close" })).toBeEnabled();
    await expect(
      canvas.getByRole("button", { name: "Reset connection" }),
    ).toBeEnabled();
    await userEvent.click(
      canvas.getByRole("button", { name: "Check saved connections" }),
    );
    await expect(args.onInspect).toHaveBeenCalledOnce();
  },
};
export const Saved: Story = {
  args: { ...wizardReviewProps, publication: { type: "SUCCESS" } },
};
export const TargetDenied: Story = {
  args: {
    identity: "APP",
    mode: "github_app",
    connection: {
      type: "VERIFIED",
      transport: "CURRENT",
      verification: {
        identity: {
          type: "app",
          app_id: "123",
          name: "Azents Test App",
          slug: "azents-test-app",
        },
        installations: [
          {
            installation_id: "7",
            account_login: null,
            account_type: null,
            account_avatar_url: null,
            status: "denied",
            message: "Installation could not be verified.",
          },
        ],
        connectivity: { status: "failed", message: null },
      },
    },
  },
};
export const TransportChanged: Story = {
  args: {
    ...TargetDenied.args,
    connection: {
      type: "VERIFIED",
      transport: "STALE",
      verification: {
        identity: {
          type: "user",
          id: 42,
          login: "fixture-user",
          avatar_url: null,
        },
        installations: [],
        connectivity: { status: "ready", message: null },
      },
    },
    stage: "FEATURES",
  },
};
export const MobileReview: Story = {
  ...FinalReview,
  parameters: { testViewport: { width: 390, height: 844 } },
  play: async ({ canvasElement }) => {
    const root = canvasElement.querySelector(".mantine-Container-root");
    if (root == null) {
      throw new Error("Wizard root is missing");
    }
    await expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth);
  },
};
