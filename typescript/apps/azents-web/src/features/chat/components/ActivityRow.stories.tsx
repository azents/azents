import { Stack } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import { ReasoningActivityRow } from "./ReasoningActivityRow";
import { SkillLoadedActivityRow } from "./SkillLoadedActivityRow";
import { ToolCallCard } from "./ToolCallCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

function CanonicalActivityRows(): React.ReactElement {
  return (
    <Stack gap={0}>
      <ToolCallCard
        toolCall={{
          id: "read-row",
          callId: "read-row",
          name: "read",
          arguments: '{"path":"/workspace/agent/README.md"}',
          result: "# README",
          status: "completed",
        }}
      />
      <ToolCallCard
        toolCall={{
          id: "generic-row",
          callId: "generic-row",
          name: "custom_tool",
          arguments: "{}",
          status: "completed",
        }}
      />
      <ReasoningActivityRow reasoningSummary="Inspect the current layout." />
      <SkillLoadedActivityRow
        name="UI review"
        content="# UI review\n\nCheck alignment."
      />
      <ProviderToolCallCard
        toolCall={{
          id: "provider-row",
          callId: "provider-row",
          name: "web_search",
          arguments: '{"query":"activity row alignment"}',
          status: "completed",
          references: [],
        }}
      />
    </Stack>
  );
}

const meta = {
  component: CanonicalActivityRows,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof CanonicalActivityRows>;

export default meta;

type Story = StoryObj<typeof meta>;

export const AlignedCollapsedRows = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rows = canvasElement.querySelectorAll("[data-activity-row]");
    await expect(rows).toHaveLength(5);
    const heights = Array.from(rows, (row) =>
      Math.round(row.getBoundingClientRect().height),
    );
    await expect(new Set(heights).size).toBe(1);
    await expect(
      canvas.getByRole("button", { name: "View raw data for Read" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "View raw data for custom_tool" }),
    ).toBeVisible();
  },
} satisfies Story;
