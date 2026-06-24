import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { pendingFiles } from "../story-fixtures";
import { AttachmentPreviewBar } from "./AttachmentPreviewBar";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const removeFile = (): void => {};

const meta = {
  component: AttachmentPreviewBar,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof AttachmentPreviewBar>;

export default meta;

type Story = StoryObj<typeof meta>;

export const AllStatuses = {
  args: {
    pendingFiles,
    onRemove: removeFile,
  },
} satisfies Story;

export const Empty = {
  args: {
    pendingFiles: [],
    onRemove: removeFile,
  },
} satisfies Story;
