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
  id: "tool-activity:story-call",
  firstMessageId: "story-tool-message-1",
  startMessageIndex: 1,
  endMessageIndex: 5,
  calls: [
    {
      type: "client",
      messageId: "story-tool-message-1",
      toolCall: completedToolCall,
    },
    {
      type: "client",
      messageId: "story-tool-message-2",
      toolCall: failedToolCall,
    },
    {
      type: "client",
      messageId: "story-tool-message-3",
      toolCall: runningToolCall,
    },
  ],
  turnCount: 3,
  reasoningSummaries: [],
  compactionCount: 0,
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

export const Collapsed = {
  args: { activity },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Activity")).toBeVisible();
    await expect(
      canvas.getByText("3 model turns · 3 tool calls · 1 failed · 1 running"),
    ).toBeVisible();
    await expect(canvas.queryByText("Tool activity")).toBeNull();
  },
} satisfies Story;

export const ExpandedGenericDetails = {
  args: { activity },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Show activity" }),
    );
    await expect(canvas.getByText("Tool activity")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Show tool calls" }),
    );
    await expect(canvas.getByText(completedToolCall.name)).toBeVisible();
    await expect(canvas.getByText(failedToolCall.name)).toBeVisible();
  },
} satisfies Story;
