import { Stack } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { createChatMessage } from "../story-fixtures";
import { ActivityMessageRow } from "./ActivityMessageRow";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import { ToolCallCard } from "./ToolCallCard";
import type { ActivityEvent } from "../toolActivityPresentation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

const reasoningEvent: ActivityEvent = {
  id: "reasoning-story",
  kind: "reasoning",
  message: createChatMessage({
    id: "reasoning-story-message",
    content: null,
    reasoningSummary:
      "Inspect the renderer hierarchy before adjusting its typography.\n\nKeep all group rows visually aligned.",
  }),
  category: { key: "reasoning", label: "reasoning" },
  status: "complete",
};

const skillEvent: ActivityEvent = {
  id: "skill-story",
  kind: "skill",
  message: createChatMessage({
    id: "skill-story-message",
    role: "skill_loaded",
    content:
      "---\nname: frontend-design\n---\n\nPreserve consistent hierarchy.",
    metadata: { name: "frontend-design" },
  }),
  category: { key: "skill", label: "skill" },
  status: "complete",
};

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

function ConsecutiveActivityItems(): ReactElement {
  return (
    <Stack gap={0} maw={760}>
      <ActivityMessageRow event={reasoningEvent} />
      <ActivityMessageRow event={skillEvent} />
      <ToolCallCard
        toolCall={{
          id: "continuous-read",
          callId: "continuous-read",
          name: "read",
          arguments:
            '{"path":"/workspace/agent/azents/src/features/chat/knownToolPresentation.ts"}',
          result: "export function knownToolPresentation() {}",
          status: "completed",
        }}
      />
      <ProviderToolCallCard
        toolCall={{
          id: "continuous-web-search",
          callId: "continuous-web-search",
          name: "web_search",
          arguments: '{"query":"Azents chat activity rendering"}',
          status: "completed",
          semanticOutput: "Found two implementation references.",
          references: [
            {
              kind: "url",
              uri: "https://example.com/activity",
              title: "Activity rendering",
              excerpt: "Renderer hierarchy and interaction patterns.",
              metadata: {},
            },
            {
              kind: "url",
              uri: "https://example.com/details",
              title: "Detail presentation",
              excerpt: "Expanded tool details for a chat timeline.",
              metadata: {},
            },
          ],
        }}
      />
      <ToolCallCard
        toolCall={{
          id: "continuous-edit",
          callId: "continuous-edit",
          name: "edit",
          arguments:
            '{"path":"/workspace/agent/azents/src/features/chat/components/ToolCallCard.tsx","old_string":"borderBottom","new_string":"shared spacing"}',
          status: "completed",
        }}
      />
      <ToolCallCard
        toolCall={{
          id: "continuous-patch",
          callId: "continuous-patch",
          name: "apply_patch",
          arguments:
            '{"base_path":"/workspace/agent/azents","patch":"*** Begin Patch\\n*** Update File: src/features/chat/components/ActivityMessageRow.tsx\\n@@\\n-old row\\n+shared row\\n*** End Patch"}',
          result: "Applied activity-row alignment.",
          resultMetadata: {
            kind: "apply_patch_result",
            changes: [
              {
                action: "update",
                path: "/workspace/agent/azents/src/features/chat/components/ActivityMessageRow.tsx",
                added_lines: 1,
                removed_lines: 1,
              },
            ],
          },
          status: "completed",
        }}
      />
      <ToolCallCard
        toolCall={{
          id: "continuous-command",
          callId: "continuous-command",
          name: "exec_command",
          arguments: '{"command":"pnpm --filter @azents/web lint"}',
          status: "running",
        }}
      />
      <ToolCallCard
        toolCall={{
          id: "continuous-generic-failure",
          callId: "continuous-generic-failure",
          name: "custom_database_query",
          arguments: '{"query":"select status from jobs"}',
          result: "Connection refused",
          status: "failed",
        }}
      />
      <ToolCallCard
        toolCall={{
          id: "continuous-present-file",
          callId: "continuous-present-file",
          name: "present_file",
          arguments:
            '{"paths":["/workspace/agent/reports/activity-review.md"]}',
          result: "Presented one file.",
          status: "completed",
          attachments: [
            {
              attachmentId: "continuous-presented-file",
              uri: "exchange://generated/activity-review.md",
              mediaType: "text/markdown",
              name: "activity-review.md",
            },
          ],
        }}
      />
      <ActivityMessageRow event={goalUpdatedEvent} />
    </Stack>
  );
}

async function expandAllActivityRows(
  canvasElement: HTMLElement,
): Promise<void> {
  const canvas = within(canvasElement);
  const buttons = canvas
    .getAllByRole("button", { expanded: false })
    .filter((button) => !button.hasAttribute("disabled"));
  for (const button of buttons) {
    await userEvent.click(button);
  }
}

export const ReasoningExpanded = {
  args: { event: reasoningEvent },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /Inspect the renderer hierarchy/ }),
    );
    await expect(
      canvas.getByText("Keep all group rows visually aligned."),
    ).toBeVisible();
  },
} satisfies Story;

export const SkillCollapsed = {
  args: { event: skillEvent },
} satisfies Story;

export const ConsecutiveCollapsedActivityItems = {
  args: { event: reasoningEvent },
  render: () => <ConsecutiveActivityItems />,
} satisfies Story;

export const ConsecutiveExpandedActivityItems = {
  args: { event: reasoningEvent },
  render: () => <ConsecutiveActivityItems />,
  play: async ({ canvasElement }) => {
    await expandAllActivityRows(canvasElement);
    await expect(
      within(canvasElement).getByText("Found two implementation references."),
    ).toBeVisible();
  },
} satisfies Story;

export const ConsecutiveMixedActivityItems = {
  args: { event: reasoningEvent },
  render: () => <ConsecutiveActivityItems />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const name of [
      /Inspect the renderer hierarchy/,
      /Web search.*Azents chat activity rendering/,
      /Applied patch.*azents/,
      /custom_database_query.*Generic details/,
    ]) {
      await userEvent.click(canvas.getByRole("button", { name }));
    }
    await expect(
      canvas.getByText("Found two implementation references."),
    ).toBeVisible();
  },
} satisfies Story;
