import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { createChatMessage } from "../story-fixtures";
import { ActivityMessageRow } from "./ActivityMessageRow";
import type { ActivityEvent } from "../toolActivityPresentation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const goalUpdatedEvent: ActivityEvent = {
  id: "goal-updated-story",
  kind: "goal-control",
  message: createChatMessage({
    id: "goal-updated-story-message",
    role: "goal_updated",
    content: null,
  }),
  category: { key: "organize", label: "organize" },
  status: "complete",
};

const externalChannelContinuationEvent: ActivityEvent = {
  id: "external-channel-continuation-story",
  kind: "goal-control",
  message: createChatMessage({
    id: "external-channel-continuation-story-message",
    role: "goal_continuation",
    content: null,
    metadata: { source: "external_channel" },
  }),
  category: { key: "organize", label: "organize" },
  status: "complete",
};

const meta = {
  component: ActivityMessageRow,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ActivityMessageRow>;

export default meta;

type Story = StoryObj<typeof meta>;

export const GoalUpdated = {
  args: { event: goalUpdatedEvent },
} satisfies Story;

export const ExternalChannelContinuation = {
  args: { event: externalChannelContinuationEvent },
} satisfies Story;
