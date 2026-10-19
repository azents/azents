import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { createChatMessage } from "../story-fixtures";
import { ActivityEventList } from "./ActivityEventList";
import type { ActivityEvent } from "@azents/session-core/toolActivityPresentation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const events: ActivityEvent[] = [
  {
    id: "nested-reasoning",
    kind: "reasoning",
    message: createChatMessage({
      content: null,
      reasoningSummary: "Inspect the nested Run items.",
    }),
    category: { key: "reasoning", label: "reasoning" },
    status: "complete",
  },
  {
    id: "nested-skill",
    kind: "skill",
    message: createChatMessage({
      role: "skill_loaded",
      content: "---\nname: ui-review\n---\n\nPreserve the product hierarchy.",
      metadata: { name: "ui-review" },
    }),
    category: { key: "skill", label: "skill" },
    status: "complete",
  },
  {
    id: "nested-read",
    kind: "tool",
    message: null,
    toolCall: {
      type: "client",
      messageId: "nested-read-message",
      toolCall: {
        id: "nested-read",
        name: "read",
        arguments: '{"path":"/workspace/agent/README.md"}',
        result: "# README",
        status: "completed",
      },
    },
    category: { key: "explore", label: "explore" },
    status: "complete",
  },
  {
    id: "nested-failure",
    kind: "tool",
    message: null,
    toolCall: {
      type: "client",
      messageId: "nested-failure-message",
      toolCall: {
        id: "nested-failure",
        name: "custom_tool",
        arguments: "{}",
        result: "Permission denied.\nThe file was not changed.",
        status: "failed",
      },
    },
    category: { key: "other", label: "other" },
    status: "failed",
  },
  {
    id: "nested-provider",
    kind: "tool",
    message: null,
    toolCall: {
      type: "provider",
      messageId: "nested-provider-message",
      toolCall: {
        id: "nested-provider",
        name: "web_search",
        arguments: '{"query":"layout"}',
        status: "running",
        references: [],
      },
    },
    category: { key: "explore", label: "explore" },
    status: "running",
  },
  {
    id: "nested-control",
    kind: "goal-control",
    message: createChatMessage({
      role: "goal_continuation",
      content: "Continue the goal.",
    }),
    category: null,
    status: "complete",
  },
];

const meta = {
  component: ActivityEventList,
  tags: ["ci-contract"],
  args: { events },
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ActivityEventList>;
export default meta;
type Story = StoryObj<typeof meta>;
export const MixedRunEvents: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rows = Array.from(
      canvasElement.querySelectorAll("[data-activity-row]"),
    );
    await expect(rows).toHaveLength(events.length);
    await expect(
      new Set(rows.map((row) => row.getBoundingClientRect().height)).size,
    ).toBe(1);
    await expect(canvas.getByLabelText("Failed")).toBeVisible();
    await expect(
      canvas.getByLabelText("Running", { exact: true }),
    ).toBeVisible();
    for (const control of canvas.getAllByRole("button", { expanded: false })) {
      await userEvent.click(control);
      await expect(control).toHaveAttribute("aria-expanded", "true");
    }
    await expect(
      await canvas.findByText("Preserve the product hierarchy."),
    ).toBeVisible();
    await expect(await canvas.findByText(/Permission denied/)).toBeVisible();
    await expect(
      canvas.getAllByRole("button", { name: /View raw data/ }),
    ).toHaveLength(3);
    await expect(
      canvasElement.querySelectorAll("[data-chat-item]"),
    ).toHaveLength(0);
    const panels = Array.from(
      canvasElement.querySelectorAll<HTMLElement>("[data-chat-detail-panel]"),
    );
    await expect(panels).toHaveLength(5);
    await expect(
      new Set(panels.map((panel) => getComputedStyle(panel).borderRadius)).size,
    ).toBe(1);
  },
};
export const Empty: Story = { args: { events: [] } };
