import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { WorkspaceSettingsHeader } from "./WorkspaceSettingsHeader";
import type { WorkspaceResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const workspace: WorkspaceResponse = {
  name: "Platform Engineering",
  handle: "platform-engineering",
  default_runtime_profile_id: null,
  default_runtime_profile_version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const meta = {
  component: WorkspaceSettingsHeader,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: { workspace },
} satisfies Meta<typeof WorkspaceSettingsHeader>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;

export const LongName = {
  args: {
    workspace: {
      ...workspace,
      name: "A very long workspace name used to verify truncation behavior",
      handle: "long-workspace-handle-for-responsive-review",
    },
  },
} satisfies Story;
