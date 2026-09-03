import { createRef } from "react";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { pendingFiles } from "../story-fixtures";
import { AttachmentPreviewBar } from "./AttachmentPreviewBar";
import type { AttachmentPreviewBarLabels } from "./AttachmentPreviewBar";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const removeFile = (): void => {};
const labels: AttachmentPreviewBarLabels = {
  removeFile: "Remove file",
  statuses: {
    pending: "Attached",
    uploading: "Uploading",
    done: "Uploaded",
    error: "Upload failed",
  },
  errors: {
    fileTooLarge: "The file is too large.",
    invalidRequest: "The upload request is invalid.",
    unauthorized: "Sign in again to upload this file.",
    forbidden: "You cannot upload this file.",
    unsupportedType: "This file type is not supported.",
    serverError: "The server could not upload this file.",
    networkError: "The network request failed.",
    invalidResponse: "The upload response was invalid.",
    unknown: "The upload failed.",
  },
};
const viewProps = {
  labels,
  maskImage: "none",
  onRemove: removeFile,
  previewUrls: new Map<string, string>(),
  scrollerRef: createRef<HTMLDivElement>(),
};

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
    ...viewProps,
    pendingFiles,
  },
} satisfies Story;

export const Empty = {
  args: {
    ...viewProps,
    pendingFiles: [],
  },
} satisfies Story;
