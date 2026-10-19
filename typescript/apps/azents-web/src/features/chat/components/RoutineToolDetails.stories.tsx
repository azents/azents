import { rem } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { knownToolPresentation } from "../knownToolPresentation";
import {
  routineCallFixture,
  routineCompletionFixture,
  routineContextFixture,
  routineDefinitionFixture,
  routineWorkFixture,
} from "../routineToolFixtures";
import { RoutineToolDetails } from "./RoutineToolDetails";
import type { RoutineToolDetail } from "../routineToolPresentation";
import type { ActiveToolCall } from "@azents/session-core/types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

function detail(call: ActiveToolCall): RoutineToolDetail {
  const projected = knownToolPresentation(call);
  if (
    projected.type !== "specialized" ||
    projected.presentation.detail?.type !== "routine"
  ) {
    throw new Error("Expected Routine story details");
  }
  return projected.presentation.detail;
}
const changed = {
  ...routineDefinitionFixture,
  content: {
    ...routineDefinitionFixture.content,
    objective: "Investigate only changes confirmed by the official dashboard.",
  },
};
const update = {
  slug: "traffic",
  expected: routineDefinitionFixture.content,
  changes: { objective: changed.content.objective },
};
const meta = {
  title: "Chat/Routine tool details",
  component: RoutineToolDetails,
  tags: ["ci-contract"],
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    detail: detail(
      routineCallFixture(
        "create_routine",
        routineDefinitionFixture.content,
        "completed",
        routineDefinitionFixture,
      ),
    ),
  },
} satisfies Meta<typeof RoutineToolDetails>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Created: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Requested work")).toBeVisible();
    await expect(canvas.getByText("Observed result")).toBeVisible();
    await expect(canvas.getAllByText("Traffic anomalies")).toHaveLength(2);
  },
};
export const Pending: Story = {
  args: {
    detail: detail(
      routineCallFixture(
        "create_routine",
        routineDefinitionFixture.content,
        "running",
        null,
      ),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Waiting for a completed result."),
    ).toBeVisible();
    await expect(canvas.queryByText("Observed result")).not.toBeInTheDocument();
  },
};
export const Updated: Story = {
  args: {
    detail: detail(
      routineCallFixture("update_routine", update, "completed", changed),
    ),
  },
};
export const RejectedUpdate: Story = {
  args: {
    detail: detail(
      routineCallFixture("update_routine", update, "failed", null),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Requested changes")).toBeVisible();
    await expect(
      canvas.getByText(
        "No completed result was observed. Requested content is not an actual result.",
      ),
    ).toBeVisible();
    await expect(canvas.queryByText("Observed result")).not.toBeInTheDocument();
  },
};
export const CancelledUpdate: Story = {
  args: {
    detail: detail(
      routineCallFixture("update_routine", update, "cancelled", null),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(
        "No completed result was observed. Requested content is not an actual result.",
      ),
    ).toBeVisible();
    await expect(canvas.queryByText("Observed result")).not.toBeInTheDocument();
  },
};
export const EmptyList: Story = {
  args: {
    detail: detail(
      routineCallFixture("list_routines", {}, "completed", { routines: [] }),
    ),
  },
};
export const MissingDefinition: Story = {
  args: {
    detail: detail(
      routineCallFixture(
        "inspect_routine",
        { slug: "traffic", record_limit: 100 },
        "completed",
        { routine: null },
      ),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("The Routine was not found or is unavailable."),
    ).toBeVisible();
  },
};
export const Deleted: Story = {
  args: {
    detail: detail(
      routineCallFixture("delete_routine", { slug: "traffic" }, "completed", {
        deleted: true,
        routine: routineDefinitionFixture,
      }),
    ),
  },
};
export const AdmittedContext: Story = {
  args: {
    detail: detail(
      routineCallFixture(
        "read_routine_context",
        { slug: "traffic", execution_id: "occurrence-a" },
        "completed",
        routineContextFixture,
      ),
    ),
  },
};
export const SilentCompletion: Story = {
  args: {
    detail: detail(
      routineCallFixture(
        "record_routine_result",
        {
          slug: "traffic",
          execution_id: "occurrence-a",
          work: routineWorkFixture,
        },
        "completed",
        { created: true, execution: routineCompletionFixture },
      ),
    ),
  },
};
export const ExistingCompletion: Story = {
  args: {
    detail: detail(
      routineCallFixture(
        "record_routine_result",
        {
          slug: "traffic",
          execution_id: "occurrence-a",
          work: {
            ...routineWorkFixture,
            result: "A new request that does not replace the saved result.",
          },
        },
        "completed",
        { created: false, execution: routineCompletionFixture },
      ),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(
        "This occurrence was already complete. Its saved result was returned without repeating notification.",
      ),
    ).toBeVisible();
    await expect(
      canvas.getByText("Traffic remains within the normal range."),
    ).toBeVisible();
    await expect(
      canvas.getByText("A new request that does not replace the saved result."),
    ).toBeVisible();
    await expect(
      canvas.queryByText("This occurrence was completed and its result saved."),
    ).not.toBeInTheDocument();
  },
};

export const DeliveryFailure: Story = {
  args: {
    detail: detail(
      routineCallFixture(
        "record_routine_result",
        {
          slug: "traffic",
          execution_id: "occurrence-a",
          work: {
            ...routineWorkFixture,
            notify: true,
            message: "Traffic needs attention.",
          },
        },
        "completed",
        {
          created: true,
          execution: {
            ...routineCompletionFixture,
            work: {
              ...routineWorkFixture,
              notify: true,
              message: "Traffic needs attention.",
            },
            delivery_status: "failed",
            delivery_error: "The current Primary connection is unavailable.",
          },
        },
      ),
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Delivery failed")).toBeVisible();
    await expect(
      canvas.getByText("The current Primary connection is unavailable."),
    ).toBeVisible();
    await expect(canvas.getAllByText("Objective finished")).toHaveLength(2);
  },
};
