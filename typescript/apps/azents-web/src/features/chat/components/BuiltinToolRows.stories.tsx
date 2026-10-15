import { Stack } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ToolCallCardContainer } from "../containers/ToolCallCardContainer";
import type { ActiveToolCall } from "@azents/session-core/types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ToolCallCardContainer,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth="45rem">
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ToolCallCardContainer>;
export default meta;
type Story = StoryObj<typeof meta>;
const session = "a".repeat(32);
const event = "b".repeat(32);
const page = {
  id: "page-1",
  task_id: "task-1",
  resource_incarnation: "incarnation-1",
  url: "https://example.com/account?token=private",
};
function call(name: string, args: object, result: object): ActiveToolCall {
  return {
    id: name,
    name,
    arguments: JSON.stringify(args),
    result: JSON.stringify(result),
    status: "completed",
  };
}
const browser = call(
  "browser_open",
  { url: page.url },
  { page, content: null },
);
export const BrowserOpen = {
  args: { toolCall: browser },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Opened browser")).toBeVisible();
    await expect(canvas.getByText("example.com")).toBeVisible();
    await expect(
      canvas.queryByText("browser_open", { exact: true }),
    ).toBeNull();
    await expect(
      canvasElement.querySelector(".tabler-icon-browser"),
    ).not.toBeNull();
  },
} satisfies Story;
export const BrowserObserve = {
  args: {
    toolCall: call(
      "browser_observe",
      { task_id: "task-1", page_id: "page-1", view: "dom" },
      { page, content: "Visible page content" },
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /^Observed browser ·/ }),
    );
    await expect(await canvas.findByText("Visible page content")).toBeVisible();
  },
} satisfies Story;
export const BrowserActRunning = {
  args: {
    toolCall: {
      ...call(
        "browser_act",
        {
          task_id: "task-1",
          page_id: "page-1",
          resource_incarnation: "incarnation-1",
          action: "fill",
          text: "private text",
        },
        {},
      ),
      status: "running",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Interacting with browser")).toBeVisible();
    await expect(canvas.queryByText("private text")).toBeNull();
  },
} satisfies Story;
export const BrowserFailure = {
  args: {
    toolCall: {
      ...browser,
      status: "failed",
      result: "Browser Runtime unavailable",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /^Opened browser ·/ }),
    );
    await expect(
      await canvas.findByText("Browser Runtime unavailable"),
    ).toBeVisible();
  },
} satisfies Story;
const builtinRows = [
  call(
    "search_sessions",
    { query: "private query" },
    { sessions: [{ session_id: session, title: "Session design discussion" }] },
  ),
  call(
    "read_session_history",
    { session_id: session },
    {
      session_id: session,
      events: [
        {
          event_id: event,
          kind: "assistant_message",
          text: "Previous discussion",
        },
      ],
    },
  ),
  call(
    "read_session_tool_result",
    { session_id: session, event_id: event },
    {
      session_id: session,
      event_id: event,
      tool: "read",
      text: "Previous result",
      next_cursor: null,
    },
  ),
  call(
    "channel_action",
    { mode: "finish", binding: "binding-1", message: "private reply" },
    { state: "finished", outcomes: [] },
  ),
  call(
    "download_external_file",
    { file: "opaque-locator", path: "/tmp/report.pdf" },
    {
      path: "/tmp/report.pdf",
      filename: "report.pdf",
      media_type: "application/pdf",
      bytes: 10,
    },
  ),
  call("list_web_services", {}, { items: [], total_count: 0 }),
  call(
    "tool_search",
    { query: "private query" },
    {
      activated_tools: [],
      requested_limit: 5,
      activation_limit: null,
      limit_reduced: false,
    },
  ),
];
export const MemoryChannelAndExistingRenderers = {
  args: { toolCall: browser },
  render: () => (
    <Stack gap="xs">
      {builtinRows.map((toolCall) => (
        <ToolCallCardContainer key={toolCall.name} toolCall={toolCall} />
      ))}
    </Stack>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const label of [
      "Searched Session history",
      "Read Session history",
      "Read previous tool result",
      "Sent channel reply",
      "Downloaded channel file",
      "Managed web service",
      "Searched tools",
    ]) {
      await expect(canvas.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(canvas.queryByText("private reply")).toBeNull();
    await expect(
      canvasElement.querySelector(".tabler-icon-messages"),
    ).not.toBeNull();
    await expect(
      canvasElement.querySelector(".tabler-icon-brain"),
    ).not.toBeNull();
  },
} satisfies Story;
