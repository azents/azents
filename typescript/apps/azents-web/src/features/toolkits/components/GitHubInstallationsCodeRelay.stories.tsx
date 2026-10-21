import { expect, within } from "storybook/test";
import { GitHubInstallationsCodeRelayView } from "./GitHubInstallationsCodeRelay";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: GitHubInstallationsCodeRelayView,
  tags: ["ci-contract"],
} satisfies Meta<typeof GitHubInstallationsCodeRelayView>;
export default meta;
export const Success = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toBeVisible();
  },
} satisfies StoryObj<typeof meta>;
