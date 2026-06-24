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
