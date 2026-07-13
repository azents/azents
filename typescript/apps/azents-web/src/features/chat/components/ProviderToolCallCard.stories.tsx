import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { imageAttachment } from "../story-fixtures";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ProviderToolCallCard,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ProviderToolCallCard>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Running = {
  args: {
    toolCall: {
      id: "provider-call-1",
      callId: "provider-call-1",
      name: "web_search",
      arguments: '{"query":"Azents"}',
      status: "running",
    },
  },
} satisfies Story;

export const CompletedWithOutputAndAttachment = {
  args: {
    toolCall: {
      id: "provider-call-2",
      callId: "provider-call-2",
      name: "image_generation",
      arguments: '{"prompt":"A reliable timeline"}',
      status: "completed",
      output: "Generated one image.",
      attachments: [imageAttachment],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Show tool details" }),
    );
    await expect(canvas.getByText("Generated one image.")).toBeVisible();
    await expect(canvas.getByText(imageAttachment.name ?? "")).toBeVisible();
  },
} satisfies Story;

export const Failed = {
  args: {
    toolCall: {
      id: "provider-call-3",
      callId: "provider-call-3",
      name: "web_search",
      arguments: "",
      status: "failed",
      output: "The provider rejected the request.",
    },
  },
} satisfies Story;
