import { expect, within } from "storybook/test";
import { GitHubAppInstallResultView } from "./GitHubAppInstallResult";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: GitHubAppInstallResultView,
  tags: ["ci-contract"],
} satisfies Meta<typeof GitHubAppInstallResultView>;
export default meta;
export const Success = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toBeVisible();
  },
} satisfies StoryObj<typeof meta>;
