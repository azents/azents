import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ExternalChannelMessage } from "./ExternalChannelMessage";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const baseSource = {
  provider: "slack",
  resourceLabel: "#incident-response / deployment thread",
  resourceType: "thread",
  senderDisplayName: "Alice Chen",
  authorType: "human",
  authorization: "authorized_invocation",
  lifecycle: "active",
  revisionKind: "original",
  providerTimestamp: "2026-07-22T01:15:00.000Z",
  originalUrl: "https://example.slack.com/archives/C1/p1",
  correctionOfRevisionId: null,
  body: "Please verify the **production rollout** and summarize any blockers.",
};

const meta = {
  component: ExternalChannelMessage,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(820)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: { source: baseSource },
} satisfies Meta<typeof ExternalChannelMessage>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Collapsed = {} satisfies Story;

export const Expanded = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = canvas.getByRole("button");
    await userEvent.tab();
    await expect(toggle).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveFocus();
    await expect(
      canvas.getByRole("link", { name: /open original message/i }),
    ).toHaveAttribute("rel", "noopener noreferrer");
  },
} satisfies Story;

export const ContextOnly = {
  args: {
    source: {
      ...baseSource,
      senderDisplayName: "Release Bot",
      authorType: "bot",
      authorization: "context_only",
      body: "Deployment 42 is waiting for approval.",
    },
  },
} satisfies Story;

export const EditedWithoutOriginalLink = {
  args: {
    source: {
      ...baseSource,
      lifecycle: "edited",
      revisionKind: "edit",
      originalUrl: null,
      correctionOfRevisionId: "revision-1",
      body: "Please verify the production rollout and focus on database locks.",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button"));
    await expect(
      canvas.getByText(/original message is unavailable/i),
    ).toBeVisible();
  },
} satisfies Story;

export const Deleted = {
  args: {
    source: {
      ...baseSource,
      lifecycle: "deleted",
      revisionKind: "delete",
      body: "[Message deleted by provider.]",
    },
  },
} satisfies Story;

export const MobileOverflow = {
  args: {
    source: {
      ...baseSource,
      resourceLabel:
        "#incident-response-with-a-very-long-channel-name / a deeply nested deployment thread",
      senderDisplayName: "A participant with a long display name",
    },
  },
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(360)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Story;
