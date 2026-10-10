import { expect, within } from "storybook/test";
import { ProviderConnectionTestFeedback } from "./ProviderConnectionTestFeedback";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/Provider fields/Connection test feedback",
  component: ProviderConnectionTestFeedback,
  args: { state: { type: "IDLE" }, preWrap: true },
} satisfies Meta<typeof ProviderConnectionTestFeedback>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByRole("alert"),
    ).not.toBeInTheDocument();
  },
};
export const Testing: Story = {
  ...Idle,
  args: { state: { type: "TESTING" } },
};
export const Successful: Story = {
  args: {
    state: {
      type: "RESULT",
      result: { success: true, message: "Fixture success." },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toHaveAttribute(
      "style",
      expect.stringContaining("--alert-bg: var(--mantine-color-green-light)"),
    );
    await expect(
      within(canvasElement).getByText("Fixture success."),
    ).toBeVisible();
  },
};
export const Rejected: Story = {
  args: {
    state: {
      type: "RESULT",
      result: { success: false, message: "Fixture rejected." },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toHaveAttribute(
      "style",
      expect.stringContaining("--alert-bg: var(--mantine-color-red-light)"),
    );
    await expect(
      within(canvasElement).getByText("Fixture rejected."),
    ).toBeVisible();
  },
};
export const TransportError: Story = {
  args: { state: { type: "ERROR", message: "Fixture transport failed." } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("alert")).toHaveAttribute(
      "style",
      expect.stringContaining("--alert-bg: var(--mantine-color-red-light)"),
    );
    await expect(
      within(canvasElement).getByText("Fixture transport failed."),
    ).toBeVisible();
  },
};
export const InlineTransportError: Story = {
  ...TransportError,
  args: { ...TransportError.args, preWrap: false },
};
