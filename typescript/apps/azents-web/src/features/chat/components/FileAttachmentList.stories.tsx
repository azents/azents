import { expect, fireEvent, userEvent, within } from "storybook/test";
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

export const GenericFileCardInteraction = {
  args: {
    files: [binaryAttachment],
    presentation: "compact",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = canvas.getByRole("button", { name: /preview/i });
    const download = canvas.getByRole("link", { name: /download/i });

    await expect(download).toHaveAttribute(
      "href",
      expect.stringContaining("/download"),
    );
    download.focus();
    await fireEvent.keyDown(download, { key: "Enter" });
    await expect(within(document.body).queryByRole("dialog")).toBeNull();

    await userEvent.click(card);
    await expect(within(document.body).getByRole("dialog")).toBeVisible();
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
