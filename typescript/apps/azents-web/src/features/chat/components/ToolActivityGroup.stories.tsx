import { Button, Stack } from "@mantine/core";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { createChatMessage } from "../story-fixtures";
import { ToolActivityGroup } from "./ToolActivityGroup";
import type { ToolActivityGroup as ToolActivityGroupModel } from "../toolActivityPresentation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const longReasoning = [
  "**Preparing the activity presentation**",
  "",
  ...Array.from(
    { length: 18 },
    (_, index) =>
      `${index + 1}. Preserve the previous reasoning interaction while keeping the grouped timeline compact.`,
  ),
].join("\n");

const longCommandOutput = Array.from(
  { length: 24 },
  (_, index) => `validation step ${index + 1}: passed`,
).join("\n");

const activity: ToolActivityGroupModel = {
  id: "activity:story-call",
  firstMessageId: "story-reasoning-message",
  startedAt: new Date(Date.now() - 12_000).toISOString(),
  startMessageIndex: 1,
  endMessageIndex: 7,
  events: [
    {
      id: "story:reasoning",
      kind: "reasoning",
      message: createChatMessage({
        id: "story-reasoning-message",
        content: null,
        reasoningSummary: longReasoning,
      }),
      category: { key: "reasoning", label: "reasoning" },
      status: "complete",
    },
    {
      id: "story:skill",
      kind: "skill",
      message: createChatMessage({
        id: "story-skill-message",
        role: "skill_loaded",
        content:
          "---\nname: frontend-design\n---\n\nPreserve compact hierarchy and the existing interaction model.",
        metadata: { name: "frontend-design" },
      }),
      category: { key: "skill", label: "skill" },
      status: "complete",
    },
    {
      id: "story:read",
      kind: "tool",
      message: null,
      toolCall: {
        type: "client",
        messageId: "story-read-message",
        toolCall: {
          id: "story-read-call",
          callId: "story-read-call",
          name: "read",
          arguments:
            '{"path":"/workspace/agent/.azents/worktrees/chat-activity-implementation/azents/typescript/apps/azents-web/src/features/chat/components/ToolCallCard.tsx"}',
          result: longCommandOutput,
          status: "completed",
        },
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
        messageId: "story-edit-message",
        toolCall: {
          id: "story-edit-call",
          callId: "story-edit-call",
          name: "edit",
          arguments:
            '{"path":"/workspace/agent/.azents/worktrees/chat-activity-implementation/azents/typescript/apps/azents-web/src/features/chat/components/activityRowPresentation.ts","old_string":"rem(48)","new_string":"rem(28)"}',
          status: "completed",
        },
      },
      category: { key: "edit", label: "edit" },
      status: "complete",
    },
    {
      id: "story:shell",
      kind: "tool",
      message: null,
      toolCall: {
        type: "client",
        messageId: "story-shell-message",
        toolCall: {
          id: "story-shell-call",
          callId: "story-shell-call",
          name: "exec_command",
          arguments: '{"command":"pnpm --filter @azents/web lint"}',
          status: "running",
        },
      },
      category: { key: "shell", label: "shell" },
      status: "running",
    },
    {
      id: "story:failed",
      kind: "tool",
      message: null,
      toolCall: {
        type: "client",
        messageId: "story-failed-message",
        toolCall: {
          id: "story-failed-call",
          callId: "story-failed-call",
          name: "custom_database_query",
          arguments: '{"query":"select status from jobs"}',
          result: "Connection refused",
          status: "failed",
        },
      },
      category: { key: "other", label: "other" },
      status: "failed",
    },
  ],
  usage: null,
};

const nextActivity: ToolActivityGroupModel = {
  id: "activity:story-next-call",
  firstMessageId: "story-next-reasoning-message",
  startedAt: new Date(Date.now() - 8_000).toISOString(),
  startMessageIndex: 8,
  endMessageIndex: 8,
  events: [
    {
      id: "story:next-reasoning",
      kind: "reasoning",
      message: createChatMessage({
        id: "story-next-reasoning-message",
        content: null,
        reasoningSummary: "Next live activity details",
      }),
      category: { key: "reasoning", label: "reasoning" },
      status: "complete",
    },
  ],
  usage: null,
};

const emptyLiveActivity: ToolActivityGroupModel = {
  id: "activity:story-empty-live",
  firstMessageId: "story-empty-live-message",
  startedAt: new Date(Date.now() - 8_000).toISOString(),
  startMessageIndex: 9,
  endMessageIndex: 9,
  events: [],
  usage: null,
};

function LiveActivityGroupTrackingDemo(): React.ReactElement {
  const [activeGroup, setActiveGroup] = useState<"initial" | "next">("initial");

  return (
    <Stack gap="sm">
      <Button onClick={() => setActiveGroup("next")}>
        Start next live group
      </Button>
      <ToolActivityGroup
        activity={activity}
        active={activeGroup === "initial"}
      />
      <ToolActivityGroup
        activity={nextActivity}
        active={activeGroup === "next"}
      />
    </Stack>
  );
}

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
    await expect(canvas.getByText("Failed 1")).toBeVisible();
    await expect(canvas.getAllByLabelText("Done")[0]).toBeVisible();
  },
} satisfies Story;

export const RestoredReasoningAndActivityDetails = {
  args: { activity },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Activity/ }));
    await userEvent.click(
      await canvas.findByRole("button", {
        name: /Preparing the activity presentation/,
      }),
    );
    await userEvent.click(
      await canvas.findByRole("button", {
        name: /Skill loaded: frontend-design/,
      }),
    );
    await userEvent.click(
      await canvas.findByRole("button", { name: /^Read · ToolCallCard\.tsx/ }),
    );
    await userEvent.click(
      await canvas.findByRole("button", {
        name: /^Edited file · activityRowPresentation\.ts/,
      }),
    );

    await expect(canvas.getByText("Thinking")).toBeVisible();
    await expect(
      canvas.getByText(
        "Preserve compact hierarchy and the existing interaction model.",
      ),
    ).toBeVisible();
    await expect(canvas.getByText("ToolCallCard.tsx")).toBeVisible();
    await expect(
      canvas.getByText(
        "/workspace/agent/.azents/worktrees/chat-activity-implementation/azents/typescript/apps/azents-web/src/features/chat/components/activityRowPresentation.ts",
      ),
    ).toBeVisible();
    await expect(canvas.getByLabelText("Running…")).toBeVisible();
    await expect(canvas.getByLabelText("Failed")).toBeVisible();
  },
} satisfies Story;

export const TracksLiveGroupDisclosure = {
  args: { activity },
  render: () => <LiveActivityGroupTrackingDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Preparing the activity presentation"),
    ).toBeVisible();

    await userEvent.click(
      canvas.getByRole("button", { name: "Start next live group" }),
    );

    const initialGroup = canvasElement.querySelector<HTMLElement>(
      '[data-tool-activity-id="activity:story-call"]',
    );
    if (initialGroup === null) {
      throw new Error("Initial activity group was not rendered");
    }
    await expect(
      within(initialGroup).queryByText("Preparing the activity presentation"),
    ).not.toBeInTheDocument();
    await expect(
      await canvas.findByText("Next live activity details"),
    ).toBeVisible();
  },
} satisfies Story;

export const ActiveWithoutDetailsHidesLiveSpinner = {
  args: { activity: emptyLiveActivity, active: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("status", { name: "Live activity is running" }),
    ).toBeNull();
  },
} satisfies Story;

export const ActiveWithDetailsShowsHeaderSpinner = {
  args: { activity, active: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("status", { name: "Live activity is running" }),
    ).toBeVisible();
  },
} satisfies Story;
