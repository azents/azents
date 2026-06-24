import { PageFooter } from "./PageFooter";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: PageFooter,
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof PageFooter>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
