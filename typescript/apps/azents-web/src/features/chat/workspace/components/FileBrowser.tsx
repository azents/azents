"use client";

/** Workspace file browser component. */
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
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
  IconArrowRight,
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
import { useCallback, useEffect, useMemo, useState } from "react";
import type { WorkspaceBrowserMode, WorkspaceEntry } from "../types";

interface FileBrowserProps {
  root: string;
  cwd: string;
  path: string;
  browserMode: WorkspaceBrowserMode;
  modes: { id: WorkspaceBrowserMode; label: string }[];
  projectEmptyState: { title: string; description: string } | null;
  manifestEntries: WorkspaceEntry[];
  entries: WorkspaceEntry[];
  directoryEntriesByPath: Record<string, WorkspaceEntry[]>;
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
  onRefresh: () => void;
  onSetBrowserMode: (mode: WorkspaceBrowserMode) => void;
  onAddProject: () => void;
}

type FileTreeNode = WorkspaceEntry & {
  children: FileTreeNode[] | null;
};

function getParentPaths(path: string, root: string): string[] {
  const parts = path.slice(root.length).split("/").filter(Boolean);
  const parents: string[] = [];
  for (let index = 1; index <= parts.length; index += 1) {
    parents.push(`${root}/${parts.slice(0, index).join("/")}`);
  }
  return parents;
}

function getRelativePath(path: string, root: string): string {
  if (!path.startsWith(root)) {
    return path;
  }
  return path.slice(root.length).replace(/^\//, "") || root;
}

function getFileExtension(name: string): string {
  const parts = name.split(".");
  return parts.length > 1 ? (parts.at(-1) ?? "").toLowerCase() : "";
}

function getFileIcon(entry: WorkspaceEntry, size: string): React.ReactElement {
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

function sortEntries(entries: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...entries].sort((a, b) => {
    if (a.kind !== b.kind) {
      return a.kind === "directory" ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });
}

function buildTree(
  cwd: string,
  manifestEntries: WorkspaceEntry[],
  entries: WorkspaceEntry[],
  directoryEntriesByPath: Record<string, WorkspaceEntry[]>,
): FileTreeNode[] {
  const knownEntriesByPath: Record<string, WorkspaceEntry[]> = {
    ...directoryEntriesByPath,
    [cwd]: manifestEntries,
  };

  for (const entry of entries) {
    const parentPath = entry.path.slice(
      0,
      Math.max(0, entry.path.lastIndexOf("/")),
    );
    if (!knownEntriesByPath[parentPath]) {
      knownEntriesByPath[parentPath] = entries;
    }
  }

  const buildChildren = (directoryPath: string): FileTreeNode[] =>
    sortEntries(knownEntriesByPath[directoryPath] ?? []).map((entry) => ({
      ...entry,
      children:
        entry.kind === "directory" && knownEntriesByPath[entry.path]
          ? buildChildren(entry.path)
          : null,
    }));

  return buildChildren(cwd);
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
          node.path,
        ])
      : [];
    const matches =
      node.name.toLowerCase().includes(normalizedQuery) ||
      node.path.toLowerCase().includes(normalizedQuery);
    if (!matches && children.length === 0) {
      return [];
    }
    for (const parent of parents) {
      expandedMatches.add(parent);
    }
    if (node.kind === "directory") {
      expandedMatches.add(node.path);
    }
    return [{ ...node, children }];
  });
}

function collectDirectoryPaths(
  nodes: FileTreeNode[],
  output = new Set<string>(),
): Set<string> {
  for (const node of nodes) {
    if (node.kind !== "directory") {
      continue;
    }
    output.add(node.path);
    collectDirectoryPaths(node.children ?? [], output);
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
  getDownloadHref: (path: string) => string;
  onToggle: (path: string) => void;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onShowInfo: (path: string) => void;
  onToggleSelectedPath: (path: string) => void;
  onCreateDirectory: (basePath: string) => void;
  onRenamePath: (entry: WorkspaceEntry) => void;
  onMovePath: (entry: WorkspaceEntry) => void;
  onDeletePath: (entry: WorkspaceEntry) => void;
  onRemoveProject: (entry: WorkspaceEntry) => void;
}

function TreeNode({
  node,
  depth,
  root,
  expanded,
  activePath,
  selectedPaths,
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
}: TreeNodeProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const theme = useMantineTheme();
  const compact = useMediaQuery(`(min-width: ${theme.breakpoints.lg})`);
  const open = expanded.has(node.path);
  const active = activePath === node.path;
  const checked = selectedPaths.has(node.path);
  const isDirectory = node.kind === "directory";
  const selectable = canSelect(node);
  const canRemoveProject = node.capabilities?.removeProject === true;
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
      onToggle(node.path);
      onOpenDirectory(node.path);
      return;
    }
    onOpenFile(node.path);
  }, [isDirectory, node.path, onOpenDirectory, onOpenFile, onToggle]);

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
        <Checkbox
          size="xs"
          checked={checked}
          disabled={!selectable}
          aria-label={t("selectPath")}
          onClick={(event) => event.stopPropagation()}
          onChange={() => onToggleSelectedPath(node.path)}
        />
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
                transition: "transform 120ms ease",
              }}
            />
          ) : null}
        </Box>
        <Box
          c={isDirectory ? "blue" : "dimmed"}
          style={{ display: "inline-flex", flexShrink: 0 }}
        >
          {isDirectory && open ? (
            <IconFolderOpen size={iconSize} />
          ) : (
            getFileIcon(node, iconSize)
          )}
        </Box>
        <Text
          size={compact ? "xs" : "sm"}
          fw={isDirectory ? 500 : 400}
          title={getRelativePath(node.path, root)}
          truncate
          style={{ flex: "1 1 auto", minWidth: 0 }}
        >
          {node.name}
        </Text>
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
            {canDelete(node) || canRemoveProject ? <Menu.Divider /> : null}
            {canRemoveProject ? (
              <Menu.Item
                color="red"
                leftSection={<IconTrash size="0.875rem" />}
                onClick={() => onRemoveProject(node)}
              >
                {t("removeProject")}
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
      {isDirectory && open
        ? node.children?.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              root={root}
              expanded={expanded}
              activePath={activePath}
              selectedPaths={selectedPaths}
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
            />
          ))
        : null}
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
  entries,
  directoryEntriesByPath,
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
  onRefresh,
  onSetBrowserMode,
  onAddProject,
}: FileBrowserProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const [query, setQuery] = useState("");
  const tree = useMemo(
    () => buildTree(cwd, manifestEntries, entries, directoryEntriesByPath),
    [cwd, directoryEntriesByPath, entries, manifestEntries],
  );
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([cwd]));
  const selectedPathSet = useMemo(
    () => new Set(selectedPaths),
    [selectedPaths],
  );

  useEffect(() => {
    setExpanded((previous) => {
      const next = new Set(previous);
      next.add(cwd);
      for (const parent of getParentPaths(path, cwd)) {
        next.add(parent);
      }
      return next;
    });
  }, [cwd, path]);

  const { displayTree, searchExpanded } = useMemo(() => {
    const expandedMatches = new Set<string>();
    return {
      displayTree: filterTree(tree, query, expandedMatches),
      searchExpanded: expandedMatches,
    };
  }, [query, tree]);
  const effectiveExpanded = query.trim() ? searchExpanded : expanded;

  const handleToggle = useCallback((directoryPath: string): void => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(directoryPath)) {
        next.delete(directoryPath);
      } else {
        next.add(directoryPath);
      }
      return next;
    });
  }, []);

  const handleExpandAll = useCallback((): void => {
    setExpanded(collectDirectoryPaths(tree));
  }, [tree]);

  const handleCollapseAll = useCallback((): void => {
    setExpanded(new Set([cwd]));
  }, [cwd]);

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
            <ActionIcon size="sm" variant="subtle">
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
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<IconFolderPlus size="0.875rem" />}
                  onClick={onAddProject}
                >
                  {t("addProject")}
                </Button>
              ) : null}
            </Stack>
          ) : (
            <>
              {!query && browserMode === "projects" ? (
                <Box px="xs" py={rem(4)}>
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
                </Box>
              ) : null}
              {displayTree.map((node) => (
                <TreeNode
                  key={node.path}
                  node={node}
                  depth={0}
                  root={root}
                  expanded={effectiveExpanded}
                  activePath={activePath}
                  selectedPaths={selectedPathSet}
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
                />
              ))}
            </>
          )}
        </Box>
      </ScrollArea>
    </Stack>
  );
}
