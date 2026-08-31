"use client";

/** Workspace file browser component. */
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  Loader,
  Menu,
  rem,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  useMantineTheme,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  IconAlertCircle,
  IconArrowRight,
  IconBrandGit,
  IconChevronDown,
  IconChevronRight,
  IconChevronUp,
  IconDotsVertical,
  IconDownload,
  IconEdit,
  IconFile,
  IconFileCode,
  IconFileDescription,
  IconFileSpreadsheet,
  IconFolder,
  IconFolderOpen,
  IconFolderPlus,
  IconInfoCircle,
  IconRefresh,
  IconSearch,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";
import { chatChevronTransition } from "../../components/collapsiblePresentation";
import { buildFileTree, type FileTreeNode } from "../fileBrowserTree";
import type {
  WorkspaceBrowserMode,
  WorkspaceDirectoryLoadState,
  WorkspaceEntry,
} from "../types";

interface FileBrowserProps {
  root: string;
  cwd: string;
  path: string;
  browserMode: WorkspaceBrowserMode;
  modes: { id: WorkspaceBrowserMode; label: string }[];
  projectEmptyState: { title: string; description: string } | null;
  manifestEntries: WorkspaceEntry[];
  directoryEntriesByPath: Record<string, WorkspaceEntry[]>;
  directoryLoadStatesByPath: Record<string, WorkspaceDirectoryLoadState>;
  selectedFilePath: string | null;
  selectedPaths: string[];
  isRefreshing: boolean;
  getDownloadHref: (path: string) => string;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onShowInfo: (path: string) => void;
  onToggleSelectedPath: (path: string) => void;
  onClearSelection: () => void;
  onBulkMove: () => void;
  onBulkDelete: () => void;
  onCreateDirectory: (basePath: string) => void;
  onRenamePath: (entry: WorkspaceEntry) => void;
  onMovePath: (entry: WorkspaceEntry) => void;
  onDeletePath: (entry: WorkspaceEntry) => void;
  onRemoveProject: (entry: WorkspaceEntry) => void;
  onDeleteWorktreeProject: (entry: WorkspaceEntry) => void;
  onRefresh: () => void;
  onSetBrowserMode: (mode: WorkspaceBrowserMode) => void;
  onAddProject: () => void;
}

function getRelativePath(path: string, root: string): string {
  if (!path.startsWith(root)) {
    return path;
  }
  return path.slice(root.length).replace(/^\//, "") || root;
}

function getBasename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1) || trimmed;
}

function isProjectRootEntry(entry: WorkspaceEntry, depth: number): boolean {
  return (
    depth === 0 &&
    (entry.source?.type === "session_project" ||
      entry.source?.type === "preview_project")
  );
}

function isSessionFolderEntry(entry: WorkspaceEntry): boolean {
  return entry.source?.type === "session_folder";
}

function getEntryDisplayName(entry: WorkspaceEntry, depth: number): string {
  if (isProjectRootEntry(entry, depth)) {
    return getBasename(entry.path);
  }
  return entry.name;
}

function getEntryDisplayPath(
  entry: WorkspaceEntry,
  depth: number,
): string | null {
  return isProjectRootEntry(entry, depth) ||
    (depth === 0 && isSessionFolderEntry(entry))
    ? entry.path
    : null;
}

function getFileExtension(name: string): string {
  const parts = name.split(".");
  return parts.length > 1 ? (parts.at(-1) ?? "").toLowerCase() : "";
}

function getFileIcon(
  entry: WorkspaceEntry,
  size: string,
  depth: number,
): React.ReactElement {
  if (isProjectRootEntry(entry, depth) && entry.repositoryType === "git") {
    return <IconBrandGit size={size} />;
  }
  if (entry.kind === "directory") {
    return <IconFolder size={size} />;
  }
  const extension = getFileExtension(entry.name);
  if (
    ["ts", "tsx", "js", "jsx", "py", "sh", "json", "css"].includes(extension)
  ) {
    return <IconFileCode size={size} />;
  }
  if (["md", "mdx", "txt"].includes(extension)) {
    return <IconFileDescription size={size} />;
  }
  if (["csv", "tsv"].includes(extension)) {
    return <IconFileSpreadsheet size={size} />;
  }
  return <IconFile size={size} />;
}

function filterTree(
  nodes: FileTreeNode[],
  query: string,
  expandedMatches: Set<string>,
  parents: string[] = [],
): FileTreeNode[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (normalizedQuery === "") {
    return nodes;
  }

  return nodes.flatMap((node) => {
    const children = node.children
      ? filterTree(node.children, query, expandedMatches, [
          ...parents,
          node.nodeId,
        ])
      : null;
    const matches =
      node.name.toLowerCase().includes(normalizedQuery) ||
      node.path.toLowerCase().includes(normalizedQuery);
    if (!matches && (children?.length ?? 0) === 0) {
      return [];
    }
    for (const parent of parents) {
      expandedMatches.add(parent);
    }
    if (node.kind === "directory") {
      expandedMatches.add(node.nodeId);
    }
    return [{ ...node, children }];
  });
}

function collectDirectoryNodeIds(
  nodes: FileTreeNode[],
  output = new Set<string>(),
): Set<string> {
  for (const node of nodes) {
    if (node.kind !== "directory") {
      continue;
    }
    output.add(node.nodeId);
    collectDirectoryNodeIds(node.children ?? [], output);
  }
  return output;
}

function canRename(entry: WorkspaceEntry): boolean {
  return entry.capabilities?.filesystemRename ?? true;
}

function canMove(entry: WorkspaceEntry): boolean {
  return entry.capabilities?.filesystemMove ?? true;
}

function canDelete(entry: WorkspaceEntry): boolean {
  return entry.capabilities?.filesystemDelete ?? true;
}

function canSelect(entry: WorkspaceEntry): boolean {
  return canMove(entry) || canDelete(entry);
}

function getIconColor(entry: WorkspaceEntry, depth: number): string {
  if (isProjectRootEntry(entry, depth) && entry.repositoryType === "git") {
    return "orange";
  }
  return entry.kind === "directory" ? "blue" : "dimmed";
}

function getStatusColor(status: WorkspaceEntry["status"]): string {
  switch (status?.value) {
    case "available":
      return "green";
    case "missing":
    case "error":
      return "red";
    case "unavailable":
      return "yellow";
    case "unchecked":
    default:
      return "gray";
  }
}

interface TreeNodeProps {
  node: FileTreeNode;
  depth: number;
  root: string;
  expanded: Set<string>;
  activePath: string | null;
  selectedPaths: Set<string>;
  directoryLoadStatesByPath: Record<string, WorkspaceDirectoryLoadState>;
  getDownloadHref: (path: string) => string;
  onToggle: (nodeId: string) => void;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onShowInfo: (path: string) => void;
  onToggleSelectedPath: (path: string) => void;
  onCreateDirectory: (basePath: string) => void;
  onRenamePath: (entry: WorkspaceEntry) => void;
  onMovePath: (entry: WorkspaceEntry) => void;
  onDeletePath: (entry: WorkspaceEntry) => void;
  onRemoveProject: (entry: WorkspaceEntry) => void;
  onDeleteWorktreeProject: (entry: WorkspaceEntry) => void;
}

function TreeNode({
  node,
  depth,
  root,
  expanded,
  activePath,
  selectedPaths,
  directoryLoadStatesByPath,
  getDownloadHref,
  onToggle,
  onOpenDirectory,
  onOpenFile,
  onShowInfo,
  onToggleSelectedPath,
  onCreateDirectory,
  onRenamePath,
  onMovePath,
  onDeletePath,
  onRemoveProject,
  onDeleteWorktreeProject,
}: TreeNodeProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const theme = useMantineTheme();
  const compact = useMediaQuery(`(min-width: ${theme.breakpoints.lg})`);
  const open = expanded.has(node.nodeId);
  const active = activePath === node.path;
  const checked = selectedPaths.has(node.path);
  const directoryLoadState =
    directoryLoadStatesByPath[node.path] ?? ({ type: "IDLE" } as const);
  const displayName = getEntryDisplayName(node, depth);
  const displayPath = getEntryDisplayPath(node, depth);
  const isDirectory = node.kind === "directory";
  const selectable = canSelect(node);
  const canRemoveProject = node.capabilities?.removeProject === true;
  const canDeleteWorktree = node.capabilities?.deleteWorktree === true;
  const rowStyle = compact
    ? {
        minHeight: rem(28),
        paddingBottom: rem(3),
        paddingLeft: rem(8 + depth * 14),
        paddingRight: rem(4),
        paddingTop: rem(3),
      }
    : {
        minHeight: rem(34),
        paddingBottom: rem(6),
        paddingLeft: rem(10 + depth * 18),
        paddingRight: rem(6),
        paddingTop: rem(6),
      };
  const iconSize = compact ? "0.875rem" : "1rem";
  const chevronSize = compact ? "0.75rem" : "0.875rem";

  const handleOpen = useCallback((): void => {
    if (isDirectory) {
      onToggle(node.nodeId);
      if (!open) {
        onOpenDirectory(node.path);
      }
      return;
    }
    onOpenFile(node.path);
  }, [
    isDirectory,
    node.nodeId,
    node.path,
    open,
    onOpenDirectory,
    onOpenFile,
    onToggle,
  ]);

  const handleSelectionTargetClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>): void => {
      event.stopPropagation();
      if (!selectable) {
        return;
      }
      onToggleSelectedPath(node.path);
    },
    [node.path, onToggleSelectedPath, selectable],
  );

  return (
    <>
      <Group
        gap={rem(6)}
        wrap="nowrap"
        role="button"
        tabIndex={0}
        onClick={handleOpen}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            handleOpen();
          }
        }}
        style={{
          alignItems: "center",
          background: active
            ? "var(--mantine-color-default-hover)"
            : "transparent",
          borderLeft: `${rem(2)} solid ${active ? "var(--mantine-color-blue-6)" : "transparent"}`,
          color: active
            ? "var(--mantine-color-blue-7)"
            : "var(--mantine-color-text)",
          cursor: "pointer",
          ...rowStyle,
          boxSizing: "border-box",
          minWidth: 0,
          width: "100%",
        }}
      >
        <Box
          onClick={handleSelectionTargetClick}
          style={{
            alignItems: "center",
            cursor: selectable ? "pointer" : "default",
            display: "inline-flex",
            flexShrink: 0,
            justifyContent: "center",
            marginBottom: rem(-6),
            marginLeft: rem(-10),
            marginTop: rem(-6),
            minHeight: rem(34),
            width: rem(40),
          }}
        >
          <Checkbox
            size="xs"
            checked={checked}
            disabled={!selectable}
            aria-label={t("selectPath")}
            onClick={(event) => event.stopPropagation()}
            onChange={() => onToggleSelectedPath(node.path)}
          />
        </Box>
        <Box
          c="dimmed"
          w={rem(16)}
          style={{
            display: "inline-flex",
            flexShrink: 0,
            justifyContent: "center",
          }}
        >
          {isDirectory ? (
            <IconChevronRight
              size={chevronSize}
              style={{
                transform: open ? "rotate(90deg)" : "none",
                transition: chatChevronTransition,
              }}
            />
          ) : null}
        </Box>
        <Box
          c={getIconColor(node, depth)}
          style={{ display: "inline-flex", flexShrink: 0 }}
        >
          {isDirectory && open && node.repositoryType !== "git" ? (
            <IconFolderOpen size={iconSize} />
          ) : (
            getFileIcon(node, iconSize, depth)
          )}
        </Box>
        <Group
          gap={rem(6)}
          wrap="nowrap"
          style={{ flex: "1 1 auto", minWidth: 0 }}
        >
          <Text
            size={compact ? "xs" : "sm"}
            fw={isDirectory ? 500 : 400}
            title={getRelativePath(node.path, root)}
            truncate
            style={{ flex: displayPath ? "0 1 auto" : "1 1 auto", minWidth: 0 }}
          >
            {displayName}
          </Text>
          {displayPath ? (
            <Text
              size={compact ? "xs" : "sm"}
              c="dimmed"
              ff="monospace"
              title={displayPath}
              truncate
              style={{ flex: "1 1 0", minWidth: 0 }}
            >
              {displayPath}
            </Text>
          ) : null}
        </Group>
        {node.status && node.status.value !== "available" ? (
          <Badge
            size="xs"
            variant={node.status.stale ? "outline" : "light"}
            color={getStatusColor(node.status)}
            title={node.status.detail ?? ""}
          >
            {t(`projectStatus.${node.status.value}`)}
          </Badge>
        ) : null}
        <Menu withinPortal position="bottom-end">
          <Menu.Target>
            <ActionIcon
              size="sm"
              variant="subtle"
              ml="auto"
              style={{ flexShrink: 0 }}
              onClick={(event) => event.stopPropagation()}
            >
              <IconDotsVertical size="0.875rem" />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown onClick={(event) => event.stopPropagation()}>
            <Menu.Item
              leftSection={<IconInfoCircle size="0.875rem" />}
              onClick={() => onShowInfo(node.path)}
            >
              {t("fileInfo")}
            </Menu.Item>
            {node.kind === "file" && (
              <Menu.Item
                component="a"
                href={getDownloadHref(node.path)}
                leftSection={<IconDownload size="0.875rem" />}
              >
                {t("download")}
              </Menu.Item>
            )}
            {node.kind === "directory" && (
              <Menu.Item
                leftSection={<IconFolderPlus size="0.875rem" />}
                onClick={() => onCreateDirectory(node.path)}
              >
                {t("newFolder")}
              </Menu.Item>
            )}
            {canRename(node) ? (
              <Menu.Item
                leftSection={<IconEdit size="0.875rem" />}
                onClick={() => onRenamePath(node)}
              >
                {t("rename")}
              </Menu.Item>
            ) : null}
            {canMove(node) ? (
              <Menu.Item
                leftSection={<IconArrowRight size="0.875rem" />}
                onClick={() => onMovePath(node)}
              >
                {t("move")}
              </Menu.Item>
            ) : null}
            {canDelete(node) || canRemoveProject || canDeleteWorktree ? (
              <Menu.Divider />
            ) : null}
            {canRemoveProject ? (
              <Menu.Item
                color="red"
                leftSection={<IconTrash size="0.875rem" />}
                onClick={() => onRemoveProject(node)}
              >
                {t("removeProject")}
              </Menu.Item>
            ) : null}
            {canDeleteWorktree ? (
              <Menu.Item
                color="red"
                leftSection={<IconTrash size="0.875rem" />}
                onClick={() => onDeleteWorktreeProject(node)}
              >
                {t("deleteWorktree")}
              </Menu.Item>
            ) : null}
            {canDelete(node) ? (
              <Menu.Item
                color="red"
                leftSection={<IconTrash size="0.875rem" />}
                onClick={() => onDeletePath(node)}
              >
                {t("delete")}
              </Menu.Item>
            ) : null}
          </Menu.Dropdown>
        </Menu>
      </Group>
      {isDirectory && open ? (
        node.children !== null ? (
          node.children.map((child) => (
            <TreeNode
              key={child.nodeId}
              node={child}
              depth={depth + 1}
              root={root}
              expanded={expanded}
              activePath={activePath}
              selectedPaths={selectedPaths}
              directoryLoadStatesByPath={directoryLoadStatesByPath}
              getDownloadHref={getDownloadHref}
              onToggle={onToggle}
              onOpenDirectory={onOpenDirectory}
              onOpenFile={onOpenFile}
              onShowInfo={onShowInfo}
              onToggleSelectedPath={onToggleSelectedPath}
              onCreateDirectory={onCreateDirectory}
              onRenamePath={onRenamePath}
              onMovePath={onMovePath}
              onDeletePath={onDeletePath}
              onRemoveProject={onRemoveProject}
              onDeleteWorktreeProject={onDeleteWorktreeProject}
            />
          ))
        ) : directoryLoadState.type === "LOADING" ? (
          <Group
            gap={rem(6)}
            role="status"
            wrap="nowrap"
            py={rem(4)}
            pl={compact ? rem(70 + depth * 14) : rem(82 + depth * 18)}
          >
            <Loader size="xs" />
            <Text c="dimmed" size="xs">
              {t("loadingDirectory")}
            </Text>
          </Group>
        ) : directoryLoadState.type === "ERROR" ? (
          <Group
            c="red"
            gap={rem(6)}
            role="alert"
            wrap="nowrap"
            py={rem(4)}
            pl={compact ? rem(70 + depth * 14) : rem(82 + depth * 18)}
          >
            <IconAlertCircle size={rem(14)} />
            <Text size="xs">
              {t("directoryLoadFailed", {
                message: directoryLoadState.message,
              })}
            </Text>
          </Group>
        ) : null
      ) : null}
    </>
  );
}

export function FileBrowser({
  root,
  cwd,
  path,
  browserMode,
  modes,
  projectEmptyState,
  manifestEntries,
  directoryEntriesByPath,
  directoryLoadStatesByPath,
  selectedFilePath,
  selectedPaths,
  isRefreshing,
  getDownloadHref,
  onOpenDirectory,
  onOpenFile,
  onShowInfo,
  onToggleSelectedPath,
  onClearSelection,
  onBulkMove,
  onBulkDelete,
  onCreateDirectory,
  onRenamePath,
  onMovePath,
  onDeletePath,
  onRemoveProject,
  onDeleteWorktreeProject,
  onRefresh,
  onSetBrowserMode,
  onAddProject,
}: FileBrowserProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const [query, setQuery] = useState("");
  const tree = useMemo(
    () => buildFileTree(cwd, manifestEntries, directoryEntriesByPath),
    [cwd, directoryEntriesByPath, manifestEntries],
  );
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const selectedPathSet = useMemo(
    () => new Set(selectedPaths),
    [selectedPaths],
  );

  const { displayTree, searchExpanded } = useMemo(() => {
    const expandedMatches = new Set<string>();
    return {
      displayTree: filterTree(tree, query, expandedMatches),
      searchExpanded: expandedMatches,
    };
  }, [query, tree]);
  const effectiveExpanded = query.trim() ? searchExpanded : expanded;

  const handleToggle = useCallback((nodeId: string): void => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  const handleExpandAll = useCallback((): void => {
    setExpanded(collectDirectoryNodeIds(tree));
  }, [tree]);

  const handleCollapseAll = useCallback((): void => {
    setExpanded(new Set());
  }, []);

  const activePath = selectedFilePath ?? path;
  const handleModeChange = useCallback(
    (value: string): void => {
      const nextMode = modes.find((mode) => mode.id === value);
      if (nextMode) {
        onSetBrowserMode(nextMode.id);
      }
    },
    [modes, onSetBrowserMode],
  );

  return (
    <Stack gap={0} h="100%" mih={0}>
      <Group
        gap="xs"
        wrap="nowrap"
        px="xs"
        py={rem(7)}
        style={{
          background: "var(--mantine-color-default)",
          borderBottom: `${rem(1)} solid var(--mantine-color-default-border)`,
        }}
      >
        <SegmentedControl
          size="xs"
          value={browserMode}
          data={modes.map((mode) => ({ label: mode.label, value: mode.id }))}
          onChange={handleModeChange}
        />
        <TextInput
          flex={`1 1 ${rem(120)}`}
          miw={0}
          size="xs"
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder={t("searchFiles")}
          leftSection={<IconSearch size="0.8125rem" />}
          rightSection={
            query ? (
              <ActionIcon
                size="xs"
                variant="subtle"
                onClick={() => setQuery("")}
              >
                <IconX size="0.6875rem" />
              </ActionIcon>
            ) : null
          }
          styles={{ input: { border: 0, background: "transparent" } }}
        />
        <Menu withinPortal position="bottom-end">
          <Menu.Target>
            <ActionIcon aria-label={t("actions")} size="sm" variant="subtle">
              <IconDotsVertical size="0.75rem" />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>
              {t("selectedCount", { count: selectedPaths.length })}
            </Menu.Label>
            <Menu.Item
              leftSection={<IconArrowRight size="0.875rem" />}
              disabled={selectedPaths.length === 0}
              onClick={onBulkMove}
            >
              {t("move")}
            </Menu.Item>
            <Menu.Item
              color="red"
              leftSection={<IconTrash size="0.875rem" />}
              disabled={selectedPaths.length === 0}
              onClick={onBulkDelete}
            >
              {t("delete")}
            </Menu.Item>
            <Menu.Item
              leftSection={<IconX size="0.875rem" />}
              disabled={selectedPaths.length === 0}
              onClick={onClearSelection}
            >
              {t("clearSelection")}
            </Menu.Item>
            <Menu.Divider />
            <Menu.Item
              leftSection={<IconChevronDown size="0.875rem" />}
              onClick={handleExpandAll}
            >
              {t("expandAll")}
            </Menu.Item>
            <Menu.Item
              leftSection={<IconChevronUp size="0.875rem" />}
              onClick={handleCollapseAll}
            >
              {t("collapseAll")}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
        <ActionIcon
          size="sm"
          variant="subtle"
          loading={isRefreshing}
          onClick={onRefresh}
        >
          <IconRefresh size="0.75rem" />
        </ActionIcon>
      </Group>

      {browserMode === "all_files" ? (
        <Group
          gap="xs"
          wrap="nowrap"
          px="sm"
          py="xs"
          style={{
            background: "var(--mantine-color-default-hover)",
            borderBottom: `${rem(1)} solid var(--mantine-color-default-border)`,
          }}
        >
          <IconFolderOpen size="0.75rem" color="var(--mantine-color-blue-6)" />
          <Text size="xs" ff="monospace" fw={600} truncate>
            {getRelativePath(cwd, root)}
          </Text>
          <Text size="xs" c="dimmed">
            ·
          </Text>
          <Text size="xs" c="dimmed" ff="monospace" truncate>
            {getRelativePath(path, root)}
          </Text>
        </Group>
      ) : null}

      <ScrollArea
        flex={1}
        mih={0}
        type="auto"
        offsetScrollbars
        styles={{ root: { minWidth: 0 }, viewport: { minWidth: 0 } }}
      >
        <Box py={rem(4)} miw={0}>
          {displayTree.length === 0 ? (
            <Stack align="center" gap="xs" py="xl" px="md">
              <Text size="sm" fw={600} ta="center">
                {query
                  ? t("noSearchResults")
                  : (projectEmptyState?.title ?? t("emptyDirectory"))}
              </Text>
              {!query && projectEmptyState ? (
                <Text size="xs" c="dimmed" ta="center">
                  {projectEmptyState.description}
                </Text>
              ) : null}
              {!query && browserMode === "projects" ? (
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<IconFolderPlus size="0.875rem" />}
                    onClick={onAddProject}
                  >
                    {t("addProject")}
                  </Button>
                </Group>
              ) : null}
            </Stack>
          ) : (
            <>
              {!query && browserMode === "projects" ? (
                <Box px="xs" py={rem(4)}>
                  <Stack gap={rem(4)}>
                    <Button
                      fullWidth
                      justify="flex-start"
                      size="xs"
                      variant="subtle"
                      leftSection={<IconFolderPlus size="0.875rem" />}
                      onClick={onAddProject}
                    >
                      {t("addProject")}
                    </Button>
                  </Stack>
                </Box>
              ) : null}
              {displayTree.map((node) => (
                <TreeNode
                  key={node.nodeId}
                  node={node}
                  depth={0}
                  root={root}
                  expanded={effectiveExpanded}
                  activePath={activePath}
                  selectedPaths={selectedPathSet}
                  directoryLoadStatesByPath={directoryLoadStatesByPath}
                  getDownloadHref={getDownloadHref}
                  onToggle={handleToggle}
                  onOpenDirectory={onOpenDirectory}
                  onOpenFile={onOpenFile}
                  onShowInfo={onShowInfo}
                  onToggleSelectedPath={onToggleSelectedPath}
                  onCreateDirectory={onCreateDirectory}
                  onRenamePath={onRenamePath}
                  onMovePath={onMovePath}
                  onDeletePath={onDeletePath}
                  onRemoveProject={onRemoveProject}
                  onDeleteWorktreeProject={onDeleteWorktreeProject}
                />
              ))}
            </>
          )}
        </Box>
      </ScrollArea>
    </Stack>
  );
}
