import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
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
import type { FileAttachment } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const galleryImages: FileAttachment[] = Array.from(
  { length: 6 },
  (_, index): FileAttachment => ({
    ...imageAttachment,
    attachmentId: `story-gallery-${index + 1}`,
    uri: `exchange://exchange/story/files/gallery-${index + 1}/original`,
    name: `gallery-${index + 1}.jpg`,
  }),
);

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

export const GalleryOverflowNavigation = {
  args: {
    files: galleryImages,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const previewTile = canvas.getByRole("button", { name: "gallery-5.jpg" });
    await expect(canvas.getByText("+2")).toBeVisible();

    await userEvent.click(previewTile);
    const body = within(document.body);
    await expect(body.getByRole("dialog")).toBeVisible();
    await expect(body.getByText("gallery-5.jpg")).toBeVisible();
    await expect(body.getByText("5 of 6")).toBeVisible();

    await fireEvent.keyDown(window, { key: "ArrowRight" });
    await expect(body.getByText("gallery-6.jpg")).toBeVisible();
    await expect(
      body.getByRole("button", { name: "Next file" }),
    ).toBeDisabled();

    await fireEvent.keyDown(window, { key: "ArrowLeft" });
    const previewSurface = body.getByLabelText("File preview");
    await fireEvent.pointerDown(previewSurface, {
      pointerId: 1,
      isPrimary: true,
      clientX: 280,
      clientY: 100,
    });
    await fireEvent.pointerUp(previewSurface, {
      pointerId: 1,
      isPrimary: true,
      clientX: 160,
      clientY: 100,
    });
    await expect(body.getByText("gallery-6.jpg")).toBeVisible();

    await fireEvent.keyDown(window, { key: "ArrowLeft" });
    await fireEvent.wheel(previewSurface, {
      deltaX: 120,
      deltaY: 0,
    });
    await expect(body.getByText("gallery-6.jpg")).toBeVisible();

    window.history.back();
    await waitFor(() =>
      expect(within(document.body).queryByRole("dialog")).toBeNull(),
    );

    const stableUrl = window.location.href;
    await userEvent.click(previewTile);
    const closeButton = body.getByRole("button", { name: "Close preview" });
    await fireEvent.click(closeButton);
    await fireEvent.click(closeButton);
    await waitFor(() =>
      expect(within(document.body).queryByRole("dialog")).toBeNull(),
    );
    await expect(window.location.href).toBe(stableUrl);

    await userEvent.click(previewTile);
    const dialog = body.getByRole("dialog");
    await fireEvent.keyDown(dialog, { key: "Escape" });
    await fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() =>
      expect(within(document.body).queryByRole("dialog")).toBeNull(),
    );
    await expect(window.location.href).toBe(stableUrl);
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
