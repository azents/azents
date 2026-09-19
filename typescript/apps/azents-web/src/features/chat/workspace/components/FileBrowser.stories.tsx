import { Box } from "@mantine/core";
import { useCallback, useState } from "react";
import {
  expect,
  fireEvent,
  fn,
  userEvent,
  waitFor,
  within,
} from "storybook/test";
import { FileBrowserContainer } from "../containers/FileBrowserContainer";
import type { WorkspaceDirectoryLoadState, WorkspaceEntry } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const root = "/workspace/agent";
const directoryPath = `${root}/slow-directory`;
const directory: WorkspaceEntry = {
  name: "slow-directory",
  path: directoryPath,
  kind: "directory",
  size: null,
  mediaType: null,
  modifiedAt: null,
};
const child: WorkspaceEntry = {
  name: "child.txt",
  path: `${directoryPath}/child.txt`,
  kind: "file",
  size: 5,
  mediaType: "text/plain",
  modifiedAt: null,
};

interface DirectoryBrowserProps {
  initialLoadState: WorkspaceDirectoryLoadState;
  resolveChildren: boolean;
  onUploadFiles?: (
    files: FileList | File[],
    destinationDirectory: string,
  ) => void;
}

function DirectoryBrowser({
  initialLoadState,
  resolveChildren,
  onUploadFiles = (): void => {},
}: DirectoryBrowserProps): React.ReactElement {
  const [entriesByPath, setEntriesByPath] = useState<
    Record<string, WorkspaceEntry[]>
  >({});
  const [loadState, setLoadState] =
    useState<WorkspaceDirectoryLoadState>(initialLoadState);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const onOpenDirectory = useCallback(
    (path: string): void => {
      if (path !== directoryPath || !resolveChildren) {
        return;
      }
      setLoadState({ type: "LOADING" });
      window.setTimeout(() => {
        setEntriesByPath({ [directoryPath]: [child] });
        setLoadState({ type: "LOADED" });
      }, 100);
    },
    [resolveChildren],
  );

  return (
    <Box h="30rem" w="28rem">
      <FileBrowserContainer
        root={root}
        cwd={root}
        path={root}
        browserMode="all_files"
        modes={[{ id: "all_files", label: "All files" }]}
        projectEmptyState={null}
        manifestEntries={[directory]}
        directoryEntriesByPath={entriesByPath}
        directoryLoadStatesByPath={{ [directoryPath]: loadState }}
        selectedFilePath={null}
        selectedPaths={[]}
        isRefreshing={false}
        getDownloadHref={() => "#"}
        onOpenDirectory={onOpenDirectory}
        onOpenFile={fn()}
        onShowInfo={fn()}
        onToggleSelectedPath={fn()}
        onClearSelection={fn()}
        onBulkMove={fn()}
        onBulkDelete={fn()}
        onCreateDirectory={fn()}
        onRenamePath={fn()}
        onMovePath={fn()}
        onDeletePath={fn()}
        onRemoveProject={fn()}
        onDeleteWorktreeProject={fn()}
        onRefresh={fn()}
        onSetBrowserMode={fn()}
        onAddProject={fn()}
        onUploadFiles={onUploadFiles}
        query={query}
        expanded={expanded}
        onQueryChange={setQuery}
        onExpandedChange={setExpanded}
      />
    </Box>
  );
}

const meta = {
  component: DirectoryBrowser,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof DirectoryBrowser>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SearchExpandedIdleDirectory = {
  args: {
    initialLoadState: { type: "IDLE" },
    resolveChildren: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByPlaceholderText("Search files…"), "slow");
    await expect(canvas.queryByText("Loading directory…")).toBeNull();
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
} satisfies Story;

export const ExpandAllIdleDirectory = {
  args: {
    initialLoadState: { type: "IDLE" },
    resolveChildren: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(canvas.getByLabelText("Actions"));
    await userEvent.click(body.getByText("Expand all"));
    await expect(canvas.queryByText("Loading directory…")).toBeNull();
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
} satisfies Story;

export const LoadingDirectory = {
  args: {
    initialLoadState: { type: "LOADING" },
    resolveChildren: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByPlaceholderText("Search files…"), "slow");
    await expect(canvas.getByText("Loading directory…")).toBeVisible();
  },
} satisfies Story;

export const FailedDirectory = {
  args: {
    initialLoadState: {
      type: "ERROR",
      message: "Runtime Runner control is unavailable.",
    },
    resolveChildren: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByPlaceholderText("Search files…"), "slow");
    await expect(
      canvas.getByText(
        "Couldn’t load directory: Runtime Runner control is unavailable.",
      ),
    ).toBeVisible();
  },
} satisfies Story;

export const AsyncDirectoryChildren = {
  args: {
    initialLoadState: { type: "IDLE" },
    resolveChildren: true,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText("slow-directory"));
    await expect(canvas.getByText("Loading directory…")).toBeVisible();
    await expect(await canvas.findByText("child.txt")).toBeVisible();
  },
} satisfies Story;

const uploadFiles =
  fn<(files: FileList | File[], destinationDirectory: string) => void>();

export const FolderUploadPickerAcceptsMultipleFiles = {
  args: {
    initialLoadState: { type: "IDLE" },
    resolveChildren: false,
    onUploadFiles: uploadFiles,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    const inputClick = fn();
    const originalInputClick = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "click",
    );
    HTMLInputElement.prototype.click = inputClick;
    try {
      await userEvent.click(canvas.getByRole("button", { name: "Actions" }));
      await expect(body.queryByText("Upload files")).toBeNull();
      await expect(body.queryByText("Change destination")).toBeNull();
      await userEvent.click(canvas.getByRole("button", { name: "Actions" }));
      await userEvent.click(
        canvas.getByRole("button", { name: "Actions (slow-directory)" }),
      );
      const uploadFilesMenuItem = await body.findByText("Upload files");
      await waitFor(() => expect(uploadFilesMenuItem).toBeVisible());
      await userEvent.click(uploadFilesMenuItem);
      await expect(inputClick).toHaveBeenCalledTimes(1);
    } finally {
      if (originalInputClick) {
        Object.defineProperty(
          HTMLInputElement.prototype,
          "click",
          originalInputClick,
        );
      }
    }
    const input = canvas.getByTestId("workspace-upload-input");
    const first = new File(["first"], "first.txt", { type: "text/plain" });
    const second = new File(["second"], "second.csv", { type: "text/csv" });

    await fireEvent.change(input, {
      target: { files: [first, second] },
    });

    await expect(uploadFiles).toHaveBeenCalledTimes(1);
    const selected = uploadFiles.mock.calls[0]?.[0];
    if (!Array.isArray(selected)) {
      throw new Error(
        "Expected the picker to pass the selected files as an array.",
      );
    }
    const selectedFiles = selected.filter(
      (file): file is File => file instanceof File,
    );
    await expect(selectedFiles.map((file) => file.name)).toEqual([
      "first.txt",
      "second.csv",
    ]);
    await expect(uploadFiles.mock.calls[0]?.[1]).toBe(directoryPath);
  },
} satisfies Story;
