import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  githubUserAuthorizationFixture,
  githubUserConnection,
  githubUserOwners,
} from "./github-user-story-fixtures";
import { GitHubUserAuthorization } from "./GitHubUserAuthorization";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: GitHubUserAuthorization,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(680)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    ...githubUserAuthorizationFixture,
    onConfirm: fn(),
    onCancel: fn(),
    onStart: fn(),
    onDisconnect: fn(),
    onMoreAccess: fn(),
  },
} satisfies Meta<typeof GitHubUserAuthorization>;
export default meta;
type Story = StoryObj<typeof meta>;
const candidate = {
  attempt_id: "current-attempt",
  account_id: 202,
  account_login: "reviewed-account",
  account_avatar_url: null,
  app_id: "42",
  source: "byoa_user",
  sharing_scope: "workspace_shared",
} as const;
export const Connected = {} satisfies Story;
export const SavedNotAuthorized = {
  args: {
    status: { type: "READY", connection: null },
    currentConnection: null,
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("No GitHub execution account is connected."),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Authorize GitHub account" }),
    );
    await expect(args.onStart).toHaveBeenCalled();
  },
} satisfies Story;
export const Waiting = {
  args: {
    setup: {
      type: "WAITING",
      attemptId: "current-attempt",
      installUrl: "https://github.com/apps/example/installations/new",
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Cancel this authorization" }),
    );
    await expect(args.onCancel).toHaveBeenCalled();
  },
} satisfies Story;
export const ReviewReplacement = {
  args: { setup: { type: "REVIEW", candidate } },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    const dialog = within(
      await page.findByRole("dialog", {
        name: "Confirm GitHub execution account",
      }),
    );
    await expect(dialog.getByText("reviewed-account")).toBeVisible();
    await expect(
      dialog.getByText(/Confirming replaces connected-user/),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Cancel this authorization" }),
    ).toHaveFocus();
    await userEvent.click(
      dialog.getByRole("button", { name: "Confirm account and sharing" }),
    );
    await expect(args.onConfirm).toHaveBeenCalled();
  },
} satisfies Story;
export const WrongAccountCancel = {
  args: { setup: { type: "REVIEW", candidate } },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    await page.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await expect(args.onCancel).toHaveBeenCalled();
  },
} satisfies Story;
export const AgentOnlyConfirmation = {
  args: {
    sharingScope: "agent_only",
    setup: {
      type: "REVIEW",
      candidate: { ...candidate, sharing_scope: "agent_only" },
    },
  },
} satisfies Story;
export const Confirming = {
  args: { setup: { type: "CONFIRMING", candidate } },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    const dialog = within(await page.findByRole("dialog"));
    await expect(
      dialog.getByRole("button", { name: "Cancel this authorization" }),
    ).toBeDisabled();
  },
} satisfies Story;
export const PopupBlocked = {
  args: { setup: { type: "ERROR", reason: "popupBlocked", attemptId: null } },
} satisfies Story;
export const PopupClosed = {
  args: { setup: { type: "ERROR", reason: "popupClosed", attemptId: null } },
} satisfies Story;
export const ExpiringAuthorizationRejected = {
  args: { setup: { type: "ERROR", reason: "incompatible", attemptId: null } },
} satisfies Story;
export const StaleAttempt = {
  args: { setup: { type: "ERROR", reason: "stale", attemptId: "old-attempt" } },
} satisfies Story;
export const LostManagementAuthority = {
  args: { setup: { type: "ERROR", reason: "authority", attemptId: null } },
} satisfies Story;
export const SharedDisconnect = {
  args: { operation: { type: "DISCONNECT_CONFIRM" } },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    const dialog = within(
      await page.findByRole("dialog", {
        name: "Disconnect this GitHub account?",
      }),
    );
    await expect(dialog.getByText(/every Agent attached/)).toBeVisible();
    await userEvent.click(
      dialog.getByRole("button", { name: "Disconnect account" }),
    );
    await expect(args.onDisconnect).toHaveBeenCalled();
  },
} satisfies Story;
export const LocallyDisconnected = {
  args: {
    status: { type: "READY", connection: null },
    currentConnection: null,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("No GitHub execution account is connected."),
    ).toBeVisible();
    await expect(
      canvas.getByText(/Local disconnection does not guarantee/),
    ).toBeVisible();
  },
} satisfies Story;
export const ConfirmedReplacement = {
  args: {
    status: {
      type: "READY",
      connection: {
        ...githubUserConnection,
        account_login: "new-active-account",
      },
    },
    currentConnection: {
      ...githubUserConnection,
      account_login: "new-active-account",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Execution account: new-active-account"),
    ).toBeVisible();
    await expect(
      canvas.queryByText("Execution account: connected-user"),
    ).not.toBeInTheDocument();
  },
} satisfies Story;
export const DisconnectRequestInterrupted = {
  args: {
    status: { type: "READY", connection: null },
    operation: { type: "ERROR", reason: "disconnectFailed" },
  },
} satisfies Story;
export const PersonalAndTwoOrganizations = {
  args: {
    access: {
      type: "READY",
      installations: githubUserOwners,
      nextCursor: "continuation",
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("connected-user/personal-notes"),
    ).toBeVisible();
    await expect(canvas.getByText("restricted-team")).toBeVisible();
    await expect(canvas.getAllByText("Partial or unknown access")).toHaveLength(
      2,
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Load more access results" }),
    );
    await expect(args.onMoreAccess).toHaveBeenCalled();
  },
} satisfies Story;
export const SavedRegistrationChanged = {
  args: { registrationDirty: true },
} satisfies Story;
export const MobileConfirmation = {
  ...ReviewReplacement,
  parameters: { testViewport: { width: 390, height: 844 } },
} satisfies Story;
