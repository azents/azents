import { expect, fn, userEvent, within } from "storybook/test";
import { LegacyAgentToolkitSection } from "./AgentToolkitSection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const cached = {
  agentToolkits: [
    {
      id: "attachment-1",
      agent_id: "agent-1",
      toolkit_id: "toolkit-1",
      toolkit_type: "github",
      created_at: "2026-10-09T00:00:00Z",
    },
  ],
  availableToolkits: [],
  selectOptions: [{ value: "available-1", label: "Available Toolkit" }],
};
const meta = {
  component: LegacyAgentToolkitSection,
  args: {
    state: { type: "READY", ...cached },
    selectedToolkitId: null,
    onSelectionChange: fn(),
    onAttach: fn(),
    onDetach: fn(),
  },
} satisfies Meta<typeof LegacyAgentToolkitSection>;
export default meta;
type Story = StoryObj<typeof meta>;

export const CachedRowsAfterError = {
  args: { state: { type: "ERROR", ...cached }, onDetach: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("toolkit-1")).toBeVisible();
    await expect(canvas.getByRole("alert")).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "Attach" })).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Detach" }));
    await expect(args.onDetach).toHaveBeenCalledWith("attachment-1");
  },
} satisfies Story;
export const CachedRowsDuringLoading = {
  ...CachedRowsAfterError,
  args: { state: { type: "LOADING", ...cached }, onDetach: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("toolkit-1")).toBeVisible();
    await expect(canvas.queryByRole("alert")).toBeNull();
    await expect(canvas.queryByRole("button", { name: "Attach" })).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Detach" }));
    await expect(args.onDetach).toHaveBeenCalledWith("attachment-1");
  },
} satisfies Story;
export const ConcurrentLoadingAndError = {
  ...CachedRowsAfterError,
  args: { state: { type: "LOADING_ERROR", ...cached }, onDetach: fn() },
} satisfies Story;
