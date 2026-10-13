import { expect, within } from "storybook/test";
import { GoogleCallback } from "./GoogleCallback";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  title: "Toolkits/Google Callback",
  component: GoogleCallback,
  args: { state: { type: "VERIFYING" }, returnPath: null },
} satisfies Meta<typeof GoogleCallback>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Verifying: Story = {};
export const StaleCallback: Story = {
  args: { state: { type: "ERROR", reason: "staleCallback" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent(
      "No account was attached and no other attempt was cancelled.",
    );
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
  },
};
export const UncertainVerification: Story = {
  args: {
    state: { type: "ERROR", reason: "verificationUncertain" },
    returnPath: "/w/test/toolkits/new",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("link", { name: "Return to the original setup" }),
    ).toHaveAttribute("href", "/w/test/toolkits/new");
    await expect(canvas.getByRole("alert")).toHaveTextContent(
      "without exchanging the code again",
    );
  },
};
