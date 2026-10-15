import { TextInput } from "@mantine/core";
import { expect, within } from "storybook/test";
import { ToolkitSetupSection } from "./ToolkitSetupSection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/Guided setup/Section",
  component: ToolkitSetupSection,
  args: {
    number: 2,
    title: "Configure access",
    description: "Keep only the access needed for your workflow.",
    children: <TextInput label="Project ID" required />,
  },
} satisfies Meta<typeof ToolkitSetupSection>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("region", { name: "2. Configure access" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("textbox", { name: "Project ID" }),
    ).toBeRequired();
    const section = canvas.getByRole("region", { name: "2. Configure access" });
    const description = canvas.getByText(
      "Keep only the access needed for your workflow.",
    );
    const luminance = (color: string): number => {
      const rgb = color.match(/[\d.]+/g)?.map(Number);
      if (rgb == null || rgb.length !== 3) {
        throw new Error(`Expected opaque computed RGB, got ${color}`);
      }
      const weights = [0.2126, 0.7152, 0.0722];
      return rgb.reduce((sum, channel, i) => {
        const value = channel / 255;
        return (
          sum +
          (value <= 0.04045
            ? value / 12.92
            : ((value + 0.055) / 1.055) ** 2.4) *
            (weights[i] ?? 0)
        );
      }, 0);
    };
    const foreground = luminance(getComputedStyle(description).color);
    const background = luminance(getComputedStyle(section).backgroundColor);
    await expect(
      (Math.max(foreground, background) + 0.05) /
        (Math.min(foreground, background) + 0.05),
    ).toBeGreaterThanOrEqual(4.5);
  },
};
