import { NextIntlClientProvider } from "next-intl";
import { expect, userEvent, within } from "storybook/test";
import frMessages from "@/i18n/fr-FR-messages";
import jaMessages from "@/i18n/ja-JP-messages";
import koMessages from "@/i18n/ko-KR-messages";
import { ToolkitPreparationGuide } from "./ToolkitPreparationGuide";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/Guided setup/Preparation",
  component: ToolkitPreparationGuide,
  args: { toolkitType: "mcp" },
} satisfies Meta<typeof ToolkitPreparationGuide>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Mcp: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Before you start")).toBeVisible();
    await expect(canvas.getByRole("link")).toHaveAttribute("target", "_blank");
    await userEvent.click(canvas.getByText("If the connection fails"));
    await expect(canvas.getByText(/Check the endpoint/)).toBeVisible();
  },
};
export const GitHub: Story = { args: { toolkitType: "github" } };
export const Google: Story = { args: { toolkitType: "google" } };
export const Notion: Story = { args: { toolkitType: "notion" } };
export const Sentry: Story = { args: { toolkitType: "sentry" } };
export const Aws: Story = { args: { toolkitType: "aws" } };
export const Gcp: Story = { args: { toolkitType: "gcp" } };
export const Analytics: Story = { args: { toolkitType: "google_analytics" } };
export const Brave: Story = { args: { toolkitType: "brave_search" } };
export const Kubernetes: Story = { args: { toolkitType: "kubernetes" } };
export const Environment: Story = {
  args: { toolkitType: "envvar" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByText("Setup order"));
    await expect(
      canvas.getByText(/There is no external connection test/),
    ).toBeVisible();
  },
};
export const UnknownProvider: Story = {
  args: { toolkitType: "test-only-provider" },
};
export const Korean: Story = {
  args: { toolkitType: "kubernetes" },
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koMessages}>
        <Story />
      </NextIntlClientProvider>
    ),
  ],
};
export const French: Story = {
  args: { toolkitType: "aws" },
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="fr-FR" messages={frMessages}>
        <Story />
      </NextIntlClientProvider>
    ),
  ],
};
export const Japanese: Story = {
  args: { toolkitType: "gcp" },
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ja-JP" messages={jaMessages}>
        <Story />
      </NextIntlClientProvider>
    ),
  ],
};
