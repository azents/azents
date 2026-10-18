import { rem } from "@mantine/core";
import { useRef, useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SessionRoutines } from "./SessionRoutines";
import type { SessionRoutinesContainerOutput } from "../containers/useSessionRoutinesContainer";
import type {
  RoutineDefinitionResponse,
  RoutineDetailResponse,
  RoutineWorkRecordResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const routine: RoutineDefinitionResponse = {
  id: "routine-1",
  slug: "routine-traffic",
  content: {
    title: "Traffic anomalies",
    objective:
      "Check the approved traffic dashboard and compare with the previous observation. Investigate meaningful anomalies; notify only when attention is needed.",
    sources: [{ type: "manual" }],
  },
  created_at: "2026-10-18T00:00:00Z",
  updated_at: "2026-10-18T00:00:00Z",
};
const other: RoutineDefinitionResponse = {
  ...routine,
  id: "routine-2",
  slug: "routine-release-news",
  content: { ...routine.content, title: "Official release news" },
};
const detail: RoutineDetailResponse = {
  routine,
  execution: {
    execution_id: "occurrence-1",
    phase: "completed",
    admitted_at: "2026-10-18T01:00:00Z",
    started_at: "2026-10-18T01:01:00Z",
    completed_at: "2026-10-18T01:05:00Z",
  },
  records: [
    {
      id: "record-1",
      routine_id: routine.id,
      execution_id: "occurrence-1",
      started_at: "2026-10-18T01:01:00Z",
      completed_at: "2026-10-18T01:05:00Z",
      work: {
        objective_outcome: "finished",
        result: "Traffic remains within the normal range. No action is needed.",
        next_hint: "Compare the next observation with this baseline.",
        notify: false,
        message: null,
      },
      delivery_status: "not_requested",
      delivery_error: null,
    },
  ],
};

const meta = {
  title: "Session/Routines",
  component: SessionRoutines,
  tags: ["ci-contract"],
  render: (args) => <WithHeadingRef {...args} />,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1100)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: { type: "LOADED", items: [routine, other] },
    detail: { type: "NONE" },
    selectedSlug: null,
    selectedTitle: null,
    detailHeading: { current: null },
    onSelect: fn(),
    onBack: fn(),
    onRefresh: fn(),
  },
} satisfies Meta<typeof SessionRoutines>;
export default meta;
type Story = StoryObj<typeof meta>;

function WithHeadingRef(
  props: SessionRoutinesContainerOutput,
): React.ReactElement {
  const heading = useRef<HTMLHeadingElement | null>(null);
  return <SessionRoutines {...props} detailHeading={heading} />;
}

export const Inventory: Story = {};
export const Loading: Story = { args: { state: { type: "LOADING" } } };
export const Empty: Story = { args: { state: { type: "LOADED", items: [] } } };
export const Unavailable: Story = {
  args: {
    state: { type: "ERROR", message: "This session is no longer available." },
  },
};
export const DetailLoading: Story = {
  args: {
    selectedSlug: routine.slug,
    selectedTitle: routine.content.title,
    detail: { type: "LOADING" },
  },
};
export const DetailUnavailable: Story = {
  args: {
    selectedSlug: routine.slug,
    selectedTitle: routine.content.title,
    detail: {
      type: "ERROR",
      message: "The Routine was removed before this read.",
    },
  },
};
export const NotExecuted: Story = {
  args: {
    selectedSlug: routine.slug,
    selectedTitle: routine.content.title,
    detail: { type: "LOADED", data: { routine, execution: null, records: [] } },
  },
};
export const IncompleteWork: Story = {
  args: {
    selectedSlug: routine.slug,
    selectedTitle: routine.content.title,
    detail: {
      type: "LOADED",
      data: {
        ...detail,
        execution: {
          execution_id: "occurrence-1",
          admitted_at: "2026-10-18T01:00:00Z",
          started_at: "2026-10-18T01:01:00Z",
          phase: "started",
          completed_at: null,
        },
        records: [],
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Work incomplete")).toBeVisible();
    await expect(canvas.queryByText("In progress")).not.toBeInTheDocument();
    await expect(
      canvas.getByText("No completed work has been recorded yet."),
    ).toBeVisible();
  },
};
export const SilentResult: Story = {
  args: {
    selectedSlug: routine.slug,
    selectedTitle: routine.content.title,
    detail: { type: "LOADED", data: detail },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const summary = canvasElement.querySelector("summary");
    if (summary === null) {
      throw new Error("Missing retained record disclosure");
    }
    await userEvent.click(summary);
    await expect(canvas.getByText("No notification requested")).toBeVisible();
    await expect(
      canvas.queryByText("Notification message"),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: /create|delete|run|edit/i }),
    ).not.toBeInTheDocument();
  },
};

const failedRecord = {
  id: "record-1",
  routine_id: routine.id,
  execution_id: "occurrence-1",
  started_at: "2026-10-18T01:01:00Z",
  completed_at: "2026-10-18T01:05:00Z",
  work: {
    objective_outcome: "failed",
    result:
      "The approved dashboard is unavailable, so the investigation could not be completed.",
    next_hint:
      "Check access to the approved dashboard before the next investigation.",
    notify: true,
    message:
      "The traffic investigation could not be completed because the source is unavailable.",
  },
  delivery_status: "failed",
  delivery_error: "The current Primary connection is unavailable.",
} satisfies RoutineWorkRecordResponse;
export const FailedObjectiveAndDelivery: Story = {
  args: {
    selectedSlug: routine.slug,
    selectedTitle: routine.content.title,
    detail: { type: "LOADED", data: { ...detail, records: [failedRecord] } },
  },
};
export const LongContent: Story = {
  args: {
    selectedSlug: routine.slug,
    selectedTitle:
      "A long ongoing objective that must wrap rather than push the Session panel beyond the viewport",
    detail: {
      type: "LOADED",
      data: {
        ...detail,
        routine: {
          ...routine,
          content: {
            ...routine.content,
            objective: `${routine.content.objective}\n${"Long_unbroken_source_identifier_".repeat(20)}\n${routine.content.objective.repeat(12)}`,
          },
        },
      },
    },
  },
};

function Interactive(
  props: SessionRoutinesContainerOutput,
): React.ReactElement {
  const [selected, setSelected] = useState(false);
  const heading = useRef<HTMLHeadingElement | null>(null);
  return (
    <SessionRoutines
      {...props}
      selectedSlug={selected ? routine.slug : null}
      selectedTitle={selected ? routine.content.title : null}
      detail={selected ? { type: "LOADED", data: detail } : { type: "NONE" }}
      detailHeading={heading}
      onSelect={(slug, trigger) => {
        props.onSelect(slug, trigger);
        setSelected(true);
      }}
      onBack={() => {
        props.onBack();
        setSelected(false);
      }}
    />
  );
}
export const KeyboardSelection: Story = {
  render: (args) => <Interactive {...args} />,
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: /Traffic anomalies/ });
    button.focus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onSelect).toHaveBeenCalled();
    await expect(
      canvas.getByRole("heading", { name: "Traffic anomalies" }),
    ).toBeVisible();
  },
};
