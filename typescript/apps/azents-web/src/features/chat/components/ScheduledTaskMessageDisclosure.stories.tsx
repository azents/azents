import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { createChatMessage } from "../story-fixtures";
import { ScheduledTaskMessageDisclosure } from "./ScheduledTaskMessageDisclosure";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "chat/ScheduledTaskMessageDisclosure",
  component: ScheduledTaskMessageDisclosure,
  args: {
    message: createChatMessage({
      id: "schedule-story",
      role: "user",
      content: [
        "Scheduled Task work is due.",
        "Title: Daily report",
        "Schedule: Every day at 7:00 AM KST",
        "Schedule details: 0 7 * * * (Asia/Seoul)",
        "Scheduled for: October 16, 2026 at 7:00 AM KST",
        "Scheduled for details: 2026-10-15T22:00:00Z",
        "Prompt:",
        "Prepare a verified report and preserve all sources.",
      ].join("\n"),
      metadata: { source: "scheduled_task", title: "Daily report" },
    }),
  },
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ScheduledTaskMessageDisclosure>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Structured: Story = {};
export const LegacyFallback: Story = {
  args: {
    message: createChatMessage({
      id: "legacy-schedule",
      role: "user",
      content: "Scheduled Task work is due.",
      metadata: { source: "scheduled_task" },
    }),
  },
};
