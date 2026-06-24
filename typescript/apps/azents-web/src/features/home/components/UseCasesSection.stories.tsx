import { UseCasesSection } from "./UseCasesSection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: UseCasesSection,
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof UseCasesSection>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
