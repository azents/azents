import { expect, fn, userEvent, within } from "storybook/test";
import { AgentListView } from "./AgentList";
import type { AgentResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: AgentListView,
  tags: ["ci-contract"],
  args: {
    handle: "acme",
    listState: { type: "READY", agents: [] },
    canManage: true,
    onDelete: fn(),
    onToggleEnabled: fn(),
    deleteOpened: false,
    closeDelete: fn(),
    handleDeleteClick: fn(),
    handleDeleteConfirm: fn(),
  },
} satisfies Meta<typeof AgentListView>;
const agent: AgentResponse = {
  id: "assistant",
  name: "Research assistant",
  description: "Research and writing",
  type: "public",
  enabled: true,
  deletion_status: null,
  avatar: null,
  selectable_model_options: [],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128000,
  effective_auto_compaction_threshold_tokens: 96000,
  model_parameters: null,
  system_prompt: null,
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  runtime_capability: "none",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "not_applicable",
  runtime_add_available: false,
  runtime_remove_available: false,
  toolkit_management_available: true,
  browser_enabled: false,
  terminal_enabled: true,
  infrastructure_terminal_enabled: true,
  workspace_terminal_enabled: true,
  effective_terminal_enabled: true,
  terminal_denied_scope: null,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  routine_check_interval_minutes: 180,
  routine_min_action_delay_minutes: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
};
export default meta;
type Story = StoryObj<typeof meta>;
export const Empty = {} satisfies Story;
export const Populated = {
  args: { listState: { type: "READY", agents: [agent] } },
} satisfies Story;
export const ReadOnly = {
  args: { canManage: false, listState: { type: "READY", agents: [agent] } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByRole("switch"),
    ).not.toBeInTheDocument();
  },
} satisfies Story;
export const Deleting = {
  args: {
    listState: {
      type: "READY",
      agents: [{ ...agent, deletion_status: "deleting" }],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("switch")).toBeDisabled();
  },
} satisfies Story;
export const Loading = {
  args: { listState: { type: "LOADING" } },
} satisfies Story;
export const Error = { args: { listState: { type: "ERROR" } } } satisfies Story;
export const ConfirmDeletion = {
  args: { deleteOpened: true },
  play: async ({ args, canvasElement }) => {
    const dialog = within(
      within(canvasElement.ownerDocument.body).getByRole("dialog"),
    );
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await expect(args.handleDeleteConfirm).toHaveBeenCalledOnce();
  },
} satisfies Story;
