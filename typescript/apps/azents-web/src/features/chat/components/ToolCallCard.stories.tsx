import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  attachmentToolCall,
  completedToolCall,
  failedToolCall,
  interruptedToolCall,
  preparingToolCall,
  runningToolCall,
} from "../story-fixtures";
import { ToolCallCard } from "./ToolCallCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ToolCallCard,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ToolCallCard>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Preparing = {
  args: {
    toolCall: preparingToolCall,
  },
} satisfies Story;

export const Running = {
  args: {
    toolCall: runningToolCall,
  },
} satisfies Story;

export const Completed = {
  args: {
    toolCall: completedToolCall,
  },
} satisfies Story;

export const Failed = {
  args: {
    toolCall: failedToolCall,
  },
} satisfies Story;

export const Interrupted = {
  args: {
    toolCall: interruptedToolCall,
  },
} satisfies Story;

export const CompletedWithAttachments = {
  args: {
    toolCall: attachmentToolCall,
  },
} satisfies Story;

export const KnownReadWithRawData = {
  args: {
    toolCall: {
      id: "known-read-story",
      callId: "known-read-story",
      name: "read",
      arguments:
        '{"path":"/workspace/agent/azents/src/features/chat/types.ts","offset":1200}',
      status: "completed",
      result: "export interface ActiveToolCall {\n  id: string;\n}",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Read")).toBeVisible();
    await expect(
      canvas.getByText("azents/src/features/chat/types.ts"),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: /Read/ }));
    await expect(
      canvas.getByText("export interface ActiveToolCall"),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "View raw data for Read" }),
    );
    await expect(within(document.body).getByText("Raw data")).toBeVisible();
  },
} satisfies Story;

export const KnownPatch = {
  args: {
    toolCall: {
      id: "known-patch-story",
      callId: "known-patch-story",
      name: "apply_patch",
      arguments:
        '{"base_path":"/workspace/agent/azents","patch":"*** Begin Patch"}',
      status: "completed",
      result: "Applied patch under /workspace/agent/azents.",
      resultMetadata: {
        kind: "apply_patch_result",
        changes: [
          {
            action: "update",
            path: "/workspace/agent/azents/src/features/chat/ToolCallCard.tsx",
            added_lines: 12,
            removed_lines: 4,
          },
        ],
      },
    },
  },
} satisfies Story;
