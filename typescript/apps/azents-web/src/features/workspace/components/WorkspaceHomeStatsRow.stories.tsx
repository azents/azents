import { WorkspaceHomeStatsRow } from "./WorkspaceHomeStatsRow";
import type { WorkspaceHomeStats } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: WorkspaceHomeStatsRow,
} satisfies Meta<typeof WorkspaceHomeStatsRow>;

export default meta;

type Story = StoryObj<typeof meta>;

const populatedStats: WorkspaceHomeStats = {
  totalAgents: 8,
  enabledAgents: 6,
  subagentsCount: 12,
};

export const Populated = {
  args: {
    stats: populatedStats,
  },
} satisfies Story;

export const Empty = {
  args: {
    stats: {
      totalAgents: 0,
      enabledAgents: 0,
      subagentsCount: 0,
    },
  },
} satisfies Story;
