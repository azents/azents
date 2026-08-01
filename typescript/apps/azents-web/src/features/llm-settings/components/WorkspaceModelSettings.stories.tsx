import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { WorkspaceModelSettings } from "./WorkspaceModelSettings";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: WorkspaceModelSettings,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(960)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "acme",
    state: { type: "READY", settings: null },
    mutationState: { type: "IDLE", error: null },
    canManage: true,
    providerOptions: [],
    onSyncCatalog: () => Promise.resolve(),
    onSubmit: () => {},
  },
} satisfies Meta<typeof WorkspaceModelSettings>;

export default meta;

type Story = StoryObj<typeof meta>;

export const LoadedOwner = {} satisfies Story;

export const LoadedReadOnly = {
  args: { canManage: false },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Error = {
  args: { state: { type: "ERROR" } },
} satisfies Story;
