import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RoutineJudgmentDisclosure } from "./RoutineJudgmentDisclosure";
import type { RoutineJudgmentMessage } from "@azents/session-core/routinePresentation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const completed: RoutineJudgmentMessage = {
  provider: "openai",
  model: "saved-model-at-call-time",
  observation: {
    type: "AVAILABLE",
    judgmentId: "judgment-1",
    status: "completed",
    error: null,
    items: [
      {
        routineId: "traffic",
        slug: "traffic",
        title: "Traffic anomalies",
        act: true,
      },
      {
        routineId: "releases",
        slug: "releases",
        title: "Official release news",
        act: false,
      },
    ],
    callUsage: {
      promptTokens: 99000,
      completionTokens: 999,
      totalTokens: 99999,
      cachedTokens: 500,
      cacheCreationTokens: null,
      reasoningTokens: null,
      costUsd: 1.25,
    },
  },
};
const failed: RoutineJudgmentMessage = {
  provider: null,
  model: null,
  observation: {
    type: "AVAILABLE",
    judgmentId: "judgment-failed",
    status: "failed",
    error: "The selected model could not be prepared for this judgment.",
    items: [
      {
        routineId: "traffic",
        slug: "traffic",
        title: "Traffic anomalies",
        act: null,
      },
    ],
    callUsage: null,
  },
};

const meta = {
  title: "Chat/Routine judgment",
  component: RoutineJudgmentDisclosure,
  tags: ["ci-contract"],
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: { judgment: completed },
} satisfies Meta<typeof RoutineJudgmentDisclosure>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Collapsed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Routine")).toBeVisible();
    await expect(canvas.getByText("Judgment completed")).not.toBeVisible();
    await expect(canvas.getByText("Judgment-call usage")).not.toBeVisible();
  },
};
export const Expansion: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const summary = canvasElement.querySelector("summary");
    if (summary === null) {
      throw new Error("Missing Routine disclosure");
    }
    await userEvent.click(summary);
    await expect(canvas.getByText("Judgment completed")).toBeVisible();
    await expect(canvas.getByText("Selected for work")).toBeVisible();
    await expect(canvas.getByText("No work selected")).toBeVisible();
    await expect(
      canvas.getByText("Total 99,999 · Input 99,000 · Output 999"),
    ).toBeVisible();
    await expect(
      canvas.getByText("This call only; ordinary turn usage is unchanged."),
    ).toBeVisible();
    await userEvent.click(summary);
    await expect(canvas.getByText("Judgment completed")).not.toBeVisible();
  },
};
export const FailureUnknownUsage: Story = {
  args: { judgment: failed },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("Routine"));
    await expect(canvas.getByText("Judgment failed")).toBeVisible();
    await expect(canvas.getByText("Call usage is unavailable.")).toBeVisible();
    await expect(canvas.getByText("No valid decision")).toBeVisible();
    await expect(
      canvas.queryByText("No work selected"),
    ).not.toBeInTheDocument();
  },
};
export const Cancelled: Story = {
  args: {
    judgment: {
      ...failed,
      observation: {
        type: "AVAILABLE",
        judgmentId: "cancelled",
        status: "cancelled",
        error: "The judgment was cancelled.",
        items: [
          {
            routineId: "traffic",
            slug: "traffic",
            title: "Traffic anomalies",
            act: null,
          },
        ],
        callUsage: null,
      },
    },
  },
};
export const Unavailable: Story = {
  args: {
    judgment: {
      provider: null,
      model: null,
      observation: { type: "UNAVAILABLE" },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("Routine"));
    await expect(
      canvas.getByText("Judgment details are unavailable."),
    ).toBeVisible();
    await expect(
      canvas.queryByText("No work selected"),
    ).not.toBeInTheDocument();
  },
};
export const LongTitles: Story = {
  args: {
    judgment: {
      ...completed,
      observation: {
        type: "AVAILABLE",
        judgmentId: "long",
        status: "completed",
        error: null,
        callUsage: null,
        items: [
          {
            routineId: "long",
            slug: "long_unbroken_source_identifier_".repeat(15),
            title:
              "A long continuing objective that must remain readable inside a narrow Session panel ".repeat(
                5,
              ),
            act: false,
          },
        ],
      },
    },
  },
};
