import { rem } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { GitHubUserOAuthCallbackResult } from "./GitHubUserOAuthCallbackResult";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: GitHubUserOAuthCallbackResult,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(480)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: { type: "LOADING" },
    returnPath: "/w/acme/toolkits/toolkit-1/edit",
  },
} satisfies Meta<typeof GitHubUserOAuthCallbackResult>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Verifying = {} satisfies Story;
export const CandidateNotYetActive = {
  args: { state: { type: "COMPLETE" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(/ready for review, not yet activated/),
    ).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: "Return to the Toolkit" }),
    ).toHaveAttribute("href", "/w/acme/toolkits/toolkit-1/edit");
  },
} satisfies Story;
export const ExpiringResponse = {
  args: { state: { type: "ERROR", reason: "incompatible" } },
} satisfies Story;
export const UnknownOriginContext = {
  args: { state: { type: "ERROR", reason: "stale" }, returnPath: null },
} satisfies Story;
export const SetupRequestInterrupted = {
  args: { state: { type: "ERROR", reason: "setupFailed" } },
} satisfies Story;
