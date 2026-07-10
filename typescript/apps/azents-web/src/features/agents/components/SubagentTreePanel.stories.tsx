import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SubagentTreePanel } from "./SubagentTreePanel";
import type {
  SubagentTreeNodeResponse,
  SubagentTreeResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const rootNode: SubagentTreeNodeResponse = {
  session_agent_id: "sa_root",
  agent_session_id: "sess_root",
  parent_session_agent_id: null,
  name: "Release coordinator",
  path: "/",
  agent_type: "private",
  status: "running",
  last_task_message: "Coordinate the release checklist and merge order.",
  last_message_sent_at: null,
  unread_result: false,
  latest_run_id: "run_root_3",
  latest_run_index: 3,
  latest_run_status: "running",
  terminal_result_event_id: null,
  terminal_result_message: null,
  children: [
    {
      session_agent_id: "sa_research",
      agent_session_id: "sess_research",
      parent_session_agent_id: "sa_root",
      name: "ci-research",
      path: "/ci-research",
      agent_type: "private",
      status: "completed",
      last_task_message: "Inspect failing workflow logs and summarize fixes.",
      last_message_sent_at: "2026-07-10T04:00:00Z",
      unread_result: true,
      latest_run_id: "run_research_1",
      latest_run_index: 1,
      latest_run_status: "completed",
      terminal_result_event_id: "evt_result_1",
      terminal_result_message:
        "The web typecheck failure comes from a stale generated API client.",
      children: [],
    },
    {
      session_agent_id: "sa_docs",
      agent_session_id: "sess_docs",
      parent_session_agent_id: "sa_root",
      name: "docs-check",
      path: "/docs-check",
      agent_type: "private",
      status: "idle",
      last_task_message: "Check whether spec docs need updates.",
      last_message_sent_at: "2026-07-10T04:05:00Z",
      unread_result: false,
      latest_run_id: "run_docs_1",
      latest_run_index: 1,
      latest_run_status: "stopped",
      terminal_result_event_id: null,
      terminal_result_message: null,
      children: [],
    },
  ],
};

const tree: SubagentTreeResponse = {
  root_session_agent_id: "sa_root",
  root_agent_session_id: "sess_root",
  current_session_agent_id: "sa_research",
  nodes: [rootNode],
};

const meta = {
  component: SubagentTreePanel,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(420)}>
        <div style={{ height: rem(680) }}>
          <Story />
        </div>
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agentId: "agent_01",
    activeSessionId: "sess_research",
    state: { type: "LOADED", tree },
    onNavigate: () => {},
  },
} satisfies Meta<typeof SubagentTreePanel>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Loaded = {} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" },
  },
} satisfies Story;

export const Empty = {
  args: {
    state: {
      type: "LOADED",
      tree: {
        ...tree,
        current_session_agent_id: "sa_root",
        nodes: [{ ...rootNode, children: [] }],
      },
    },
  },
} satisfies Story;

export const Error = {
  args: {
    state: {
      type: "ERROR",
      message: "Failed to load subagent tree",
    },
  },
} satisfies Story;
