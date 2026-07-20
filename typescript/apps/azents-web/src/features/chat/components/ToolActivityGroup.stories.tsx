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

const specializedActivity: ToolActivityGroupModel = {
  id: "tool-activity:specialized-story",
  firstMessageId: "specialized-message-1",
  startMessageIndex: 1,
  endMessageIndex: 3,
  calls: [
    {
      type: "client",
      messageId: "specialized-message-1",
      toolCall: {
        id: "read-call",
        name: "read",
        arguments: JSON.stringify({ path: "/workspace/agent/project/a.ts" }),
        result: "file content",
        status: "completed",
      },
    },
    {
      type: "client",
      messageId: "specialized-message-2",
      toolCall: {
        id: "exec-call",
        name: "exec_command",
        arguments: JSON.stringify({ command: "pnpm test" }),
        result: "52 tests passed",
        status: "completed",
      },
    },
    {
      type: "client",
      messageId: "specialized-message-3",
      toolCall: {
        id: "edit-call",
        name: "edit",
        arguments: JSON.stringify({
          path: "/workspace/agent/project/a.ts",
          old_string: "before",
          new_string: "after",
        }),
        result: "updated",
        status: "completed",
      },
    },
  ],
  turnCount: 2,
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
    await expect(canvas.getByText("Other tool activity")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", {
        name: "Show tool calls: Other tool activity",
      }),
    );
    await expect(canvas.getByText(completedToolCall.name)).toBeVisible();
    await expect(canvas.getByText(failedToolCall.name)).toBeVisible();
  },
} satisfies Story;

export const SpecializedPhaseSummaries = {
  args: { activity: specializedActivity },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Show activity" }),
    );
    await expect(canvas.getByText("Inspected resources")).toBeVisible();
    await expect(canvas.getByText("Ran commands")).toBeVisible();
    await expect(canvas.getByText("Changed files")).toBeVisible();
  },
} satisfies Story;
