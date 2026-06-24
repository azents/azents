import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  binaryAttachment,
  expiredAttachment,
  imageAttachment,
  textAttachment,
  unavailableAttachment,
  unsupportedUriAttachment,
} from "../story-fixtures";
import { FileAttachmentList } from "./FileAttachmentList";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: FileAttachmentList,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof FileAttachmentList>;

export default meta;

type Story = StoryObj<typeof meta>;

export const MixedFiles = {
  args: {
    files: [imageAttachment, textAttachment, binaryAttachment],
  },
} satisfies Story;

export const TextPreviewOnly = {
  args: {
    files: [textAttachment],
  },
} satisfies Story;

export const UnsupportedUri = {
  args: {
    files: [unsupportedUriAttachment],
  },
} satisfies Story;

export const UnavailableFiles = {
  args: {
    files: [expiredAttachment, unavailableAttachment],
  },
} satisfies Story;

export const Empty = {
  args: {
    files: [],
  },
} satisfies Story;
