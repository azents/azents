import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  completedToolCall,
  failedToolCall,
  runningToolCall,
} from "../story-fixtures";
import { ToolActivityGroup } from "./ToolActivityGroup";
import type { ToolActivityGroup as ToolActivityGroupModel } from "../toolActivityPresentation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const activity: ToolActivityGroupModel = {
  id: "activity:story-call",
  firstMessageId: "story-tool-message-1",
  startMessageIndex: 1,
  endMessageIndex: 3,
  events: [
    {
      id: "story:explore",
      kind: "tool",
      message: null,
      toolCall: {
        type: "client",
        messageId: "story-tool-message-1",
        toolCall: completedToolCall,
      },
      category: { key: "explore", label: "explore" },
      status: "complete",
    },
    {
      id: "story:edit",
      kind: "tool",
      message: null,
      toolCall: {
        type: "client",
        messageId: "story-tool-message-2",
        toolCall: failedToolCall,
      },
      category: { key: "edit", label: "edit" },
      status: "failed",
    },
    {
      id: "story:shell",
      kind: "tool",
      message: null,
      toolCall: {
        type: "client",
        messageId: "story-tool-message-3",
        toolCall: runningToolCall,
      },
      category: { key: "shell", label: "shell" },
      status: "running",
    },
  ],
  usage: null,
};

const meta = {
  component: ToolActivityGroup,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth="45rem">
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ToolActivityGroup>;

export default meta;

type Story = StoryObj<typeof meta>;

export const CollapsedWithAttention = {
  args: { activity },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Activity")).toBeVisible();
    await expect(canvas.getByLabelText("Failed")).toBeVisible();
  },
} satisfies Story;

export const OrderedDetails = {
  args: { activity },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Activity/ }));
    await expect(canvas.getByText(completedToolCall.name)).toBeVisible();
    await expect(canvas.getByText(failedToolCall.name)).toBeVisible();
    await expect(canvas.getByText(runningToolCall.name)).toBeVisible();
  },
} satisfies Story;
