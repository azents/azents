import { Box, Stack } from "@mantine/core";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { standardDisclosureMessages } from "../chatPresentationFixtures";
import { ProviderToolCallCardContainer } from "../containers/ProviderToolCallCardContainer";
import { ToolCallCardContainer } from "../containers/ToolCallCardContainer";
import { createChatMessage } from "../story-fixtures";
import { ChatTimelineItem } from "./ChatTimelineItem";
import { CompactionDivider } from "./CompactionDivider";
import { CompactionIndicator } from "./CompactionIndicator";
import { MessageBubble } from "./MessageBubble";
import { ReasoningActivityRow } from "./ReasoningActivityRow";
import { SkillLoadedActivityRow } from "./SkillLoadedActivityRow";
import { ToolActivityGroup } from "./ToolActivityGroup";
import type { ToolActivityGroup as ActivityGroup } from "@azents/session-core/toolActivityPresentation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const activity: ActivityGroup = {
  id: "presentation-activity",
  firstMessageId: "presentation-reasoning",
  startedAt: "2026-10-19T00:00:00Z",
  startMessageIndex: 0,
  endMessageIndex: 0,
  usage: null,
  events: [
    {
      id: "presentation-reasoning",
      kind: "reasoning",
      message: createChatMessage({
        id: "presentation-reasoning",
        reasoningSummary: "Check the official sources and retain the outcome.",
      }),
      category: { key: "reasoning", label: "reasoning" },
      status: "complete",
    },
  ],
};

function Transcript(): React.ReactElement {
  return (
    <Stack gap={0}>
      <MessageBubble
        message={createChatMessage({
          id: "presentation-judgment",
          role: "routine_judgment",
          content: null,
          routineJudgment: {
            provider: "openai",
            model: "saved-model",
            observation: {
              type: "AVAILABLE",
              judgmentId: "presentation-judgment",
              status: "completed",
              error: null,
              items: [
                {
                  routineId: "traffic",
                  slug: "traffic",
                  title: "Traffic anomalies",
                  act: true,
                },
              ],
              callUsage: null,
            },
          },
        })}
      />
      <MessageBubble
        message={createChatMessage({
          id: "presentation-work",
          role: "routine_trigger",
          routineInput: {
            content: "Check traffic and record a silent result.",
            executions: [],
          },
        })}
      />
      <ToolActivityGroup activity={activity} />
      <MessageBubble
        message={createChatMessage({
          id: "presentation-answer",
          content:
            "Both checks are complete.\n\n- **Traffic:** no meaningful change.\n- **Release news:** no official announcement.\n\nI will keep watching for meaningful updates.",
        })}
      />
    </Stack>
  );
}

const meta = {
  tags: ["ci-contract"],
  title: "Chat/Presentation",
  render: () => <Transcript />,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Box data-presentation-transcript>
          <Story />
        </Box>
      </StorybookCanvas>
    ),
  ],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;
export const TranscriptSequence: Story = {};

export const AllDisclosureRoutes: Story = {
  tags: ["ci-contract"],
  render: () => (
    <Stack gap={0}>
      {standardDisclosureMessages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      <ToolActivityGroup activity={activity} />
      <ChatTimelineItem kind="activity">
        <ReasoningActivityRow reasoningSummary="Inspect the current layout." />
      </ChatTimelineItem>
      <ChatTimelineItem kind="activity">
        <SkillLoadedActivityRow
          name="UI review"
          content="# Review\n\nCheck alignment."
        />
      </ChatTimelineItem>
      <ChatTimelineItem kind="activity">
        <ToolCallCardContainer
          toolCall={{
            id: "standard-read",
            name: "read",
            arguments: '{"path":"/workspace/agent/README.md"}',
            result: "# README",
            status: "completed",
          }}
        />
      </ChatTimelineItem>
      <ChatTimelineItem kind="activity">
        <ProviderToolCallCardContainer
          toolCall={{
            id: "standard-search",
            name: "web_search",
            arguments: '{"query":"layout"}',
            references: [],
            status: "completed",
          }}
        />
      </ChatTimelineItem>
      <CompactionDivider content="Retained conversation context." />
      <CompactionIndicator />
    </Stack>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const headers = Array.from(
      canvasElement.querySelectorAll<HTMLElement>("[data-chat-row-header]"),
    );
    await expect(headers).toHaveLength(14);
    const reference = headers[0];
    if (!reference) {
      throw new Error("Missing canonical row");
    }
    const rowStyle = getComputedStyle(
      reference.querySelector("span") ?? reference,
    );
    for (const header of headers) {
      await expect(header.getBoundingClientRect().height).toBe(
        reference.getBoundingClientRect().height,
      );
      const style = getComputedStyle(header.querySelector("span") ?? header);
      await expect([
        style.fontSize,
        style.fontWeight,
        style.lineHeight,
      ]).toEqual([rowStyle.fontSize, rowStyle.fontWeight, rowStyle.lineHeight]);
      const icon = header.querySelector("[data-chat-row-icon]");
      const canonicalIcon = reference.querySelector("[data-chat-row-icon]");
      await expect(icon?.getBoundingClientRect().x).toBe(
        canonicalIcon?.getBoundingClientRect().x,
      );
    }
    const controls = canvas.getAllByRole("button", { expanded: false });
    for (const control of controls) {
      if (!control.hasAttribute("aria-controls")) {
        continue;
      }
      control.focus();
      await userEvent.keyboard("{Enter}");
      await expect(control).toHaveAttribute("aria-expanded", "true");
      await expect(
        document.getElementById(control.getAttribute("aria-controls") ?? ""),
      ).not.toBeNull();
      await userEvent.keyboard(" ");
      await waitFor(() =>
        expect(control).toHaveAttribute("aria-expanded", "false"),
      );
      await expect(control).toHaveFocus();
    }
    const channel = canvas.getByRole("button", {
      name: /Expand external message from/,
    });
    await userEvent.click(channel);
    await expect(
      await canvas.findByRole("link", { name: /original/i }),
    ).toHaveAttribute("href", "https://example.com/message");
  },
};
