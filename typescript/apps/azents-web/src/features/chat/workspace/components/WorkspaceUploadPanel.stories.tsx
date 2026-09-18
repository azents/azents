import { Box } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { useWorkspacePanelTranslations } from "../containers/useWorkspacePanelTranslations";
import { WorkspaceUploadPanel } from "./WorkspaceUploadPanel";
import type { WorkspaceUploadRow } from "../workspaceUploadTypes";
import type { WorkspaceUploadPanelProps } from "./WorkspaceUploadPanel";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

type UploadPanelStoryProps = Omit<WorkspaceUploadPanelProps, "t">;

function UploadPanelStory(props: UploadPanelStoryProps): React.ReactElement {
  const t = useWorkspacePanelTranslations();
  return (
    <Box maw="36rem" p="md">
      <WorkspaceUploadPanel {...props} t={t} />
    </Box>
  );
}

const activeRow: WorkspaceUploadRow = {
  id: "upload-active",
  filename: "dataset.csv",
  destinationPath: "/workspace/agent/project/dataset.csv",
  expectedSize: 5_242_880,
  phase: "uploading",
  progress: 48,
  transferredBytes: 2_516_582,
  uploadId: "upload-active",
  revision: 1,
  currentDeliveryNumber: null,
  failure: null,
  errorMessage: null,
  retryAvailable: false,
  serverRetryAvailable: false,
  overwriteAvailable: false,
  conflictPrecondition: null,
};

const succeededRow: WorkspaceUploadRow = {
  ...activeRow,
  id: "upload-succeeded",
  filename: "README-upload.md",
  destinationPath: "/workspace/agent/project/README-upload.md",
  expectedSize: 2_048,
  phase: "succeeded",
  progress: 100,
  transferredBytes: 2_048,
  uploadId: "upload-succeeded",
  revision: 4,
  currentDeliveryNumber: 1,
};

const cancelledRow: WorkspaceUploadRow = {
  ...activeRow,
  id: "upload-cancelled",
  filename: "cancelled.bin",
  destinationPath: "/workspace/agent/project/cancelled.bin",
  expectedSize: 1_048_576,
  phase: "cancelled",
  progress: 18,
  transferredBytes: 188_743,
  uploadId: "upload-cancelled",
  revision: 3,
  currentDeliveryNumber: null,
  failure: "cancelled",
  retryAvailable: false,
  serverRetryAvailable: false,
  overwriteAvailable: false,
  conflictPrecondition: null,
};

const conflictRow: WorkspaceUploadRow = {
  ...activeRow,
  id: "upload-conflict",
  filename: "report.json",
  destinationPath: "/workspace/agent/project/report.json",
  expectedSize: 512,
  phase: "conflicted",
  progress: 75,
  transferredBytes: 512,
  uploadId: "upload-conflict",
  revision: 5,
  currentDeliveryNumber: 1,
  failure: "destination_conflict",
  retryAvailable: true,
  serverRetryAvailable: true,
  overwriteAvailable: true,
  conflictPrecondition: "AQI",
};

const failedRow: WorkspaceUploadRow = {
  ...activeRow,
  id: "upload-failed",
  filename: "notes.txt",
  destinationPath: "/workspace/agent/project/notes.txt",
  expectedSize: 128,
  phase: "failed",
  progress: 20,
  transferredBytes: 0,
  uploadId: null,
  revision: null,
  failure: "transfer",
  errorMessage: "The storage request was unavailable.",
  retryAvailable: true,
};

const onCancel = fn();
const onRetry = fn();
const onDismiss = fn();

const meta = {
  component: UploadPanelStory,
  parameters: { layout: "fullscreen" },
  args: {
    rows: [],
    onCancel,
    onRetry,
    onDismiss,
  },
} satisfies Meta<typeof UploadPanelStory>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty = {} satisfies Story;

export const LifecycleStates = {
  args: {
    rows: [activeRow, succeededRow, cancelledRow, conflictRow, failedRow],
  },
} satisfies Story;

export const Cancelled = {
  args: {
    rows: [cancelledRow],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Cancelled")).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "Cancel" })).toBeNull();
    await expect(
      canvas.getByRole("button", { name: "Dismiss upload" }),
    ).toBeVisible();
  },
} satisfies Story;

export const Actions = {
  args: {
    rows: [activeRow, succeededRow, cancelledRow, conflictRow, failedRow],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await expect(onCancel).toHaveBeenCalledWith("upload-active");

    const retryButtons = canvas.getAllByRole("button", { name: "Retry" });
    const firstRetryButton = retryButtons.at(0);
    if (!firstRetryButton) {
      throw new Error("Expected a retry button for the conflicted upload.");
    }
    await userEvent.click(firstRetryButton);
    await expect(onRetry).toHaveBeenCalledWith("upload-conflict", false);

    await userEvent.click(
      canvas.getByRole("button", { name: "Overwrite and retry" }),
    );
    await expect(onRetry).toHaveBeenCalledWith("upload-conflict", true);

    const dismissButtons = canvas.getAllByRole("button", {
      name: "Dismiss upload",
    });
    const firstDismissButton = dismissButtons.at(0);
    if (!firstDismissButton) {
      throw new Error("Expected a dismiss button for the succeeded upload.");
    }
    await userEvent.click(firstDismissButton);
    await expect(onDismiss).toHaveBeenCalledWith("upload-succeeded");
  },
} satisfies Story;
