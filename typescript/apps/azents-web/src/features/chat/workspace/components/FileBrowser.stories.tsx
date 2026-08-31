import { Box } from "@mantine/core";
import { useCallback, useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { FileBrowser } from "./FileBrowser";
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
}

function DirectoryBrowser({
  initialLoadState,
  resolveChildren,
}: DirectoryBrowserProps): React.ReactElement {
  const [entriesByPath, setEntriesByPath] = useState<
    Record<string, WorkspaceEntry[]>
  >({});
  const [loadState, setLoadState] =
    useState<WorkspaceDirectoryLoadState>(initialLoadState);
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
      <FileBrowser
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
