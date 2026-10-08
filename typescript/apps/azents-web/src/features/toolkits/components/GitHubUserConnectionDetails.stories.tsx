import { rem } from "@mantine/core";
import { expect } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  githubUserAuthorizationFixture,
  githubUserConnection,
  githubUserOwners,
} from "./github-user-story-fixtures";
import { GitHubUserConnectionDetails } from "./GitHubUserConnectionDetails";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: GitHubUserConnectionDetails,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(680)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: githubUserAuthorizationFixture,
} satisfies Meta<typeof GitHubUserConnectionDetails>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Loading = {
  args: { status: { type: "LOADING" } },
  play: async ({ canvas }) => {
    await expect(
      canvas.getByRole("status", { name: "Loading GitHub account status…" }),
    ).toBeVisible();
  },
} satisfies Story;
export const StatusError = {
  args: { status: { type: "ERROR" } },
} satisfies Story;
export const AccessUnknown = {} satisfies Story;
export const AccessLoading = {
  args: { access: { type: "LOADING" } },
} satisfies Story;
export const NoObservedOwners = {
  args: { access: { type: "READY", installations: [], nextCursor: null } },
} satisfies Story;
export const PartialMultiOrganization = {
  args: {
    access: {
      type: "READY",
      installations: githubUserOwners,
      nextCursor: "continuation",
    },
  },
} satisfies Story;
export const NextPageLoading = {
  args: {
    access: {
      type: "MORE",
      installations: githubUserOwners,
      nextCursor: "continuation",
    },
  },
} satisfies Story;
export const NextPageFailed = {
  args: {
    access: {
      type: "ERROR",
      installations: githubUserOwners,
      nextCursor: "continuation",
    },
  },
} satisfies Story;
export const ReconnectRequired = {
  args: {
    status: {
      type: "READY",
      connection: {
        ...githubUserConnection,
        status: "reconnect_required",
        failure_reason: "authentication_failed",
      },
    },
  },
} satisfies Story;
export const LocallyDisconnected = {
  args: { status: { type: "READY", connection: null } },
} satisfies Story;
