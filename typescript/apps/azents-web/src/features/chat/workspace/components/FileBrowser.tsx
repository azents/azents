"use client";

/** Workspace file browser component. */
import {
  ActionIcon,
  Box,
  Group,
  rem,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Tooltip,
  useMantineTheme,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  IconChevronDown,
  IconChevronRight,
  IconChevronUp,
  IconFile,
  IconFileCode,
  IconFileDescription,
  IconFileSpreadsheet,
  IconFolder,
  IconFolderOpen,
  IconRefresh,
  IconSearch,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { WorkspaceEntry } from "../types";

interface FileBrowserProps {
  root: string;
  cwd: string;
  path: string;
  manifestEntries: WorkspaceEntry[];
  entries: WorkspaceEntry[];
  directoryEntriesByPath: Record<string, WorkspaceEntry[]>;
  selectedFilePath: string | null;
  isRefreshing: boolean;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onRefresh: () => void;
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
    [cwd]: directoryEntriesByPath[cwd] ?? manifestEntries,
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

interface TreeNodeProps {
  node: FileTreeNode;
  depth: number;
  root: string;
  expanded: Set<string>;
  activePath: string | null;
  onToggle: (path: string) => void;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
}

function TreeNode({
  node,
  depth,
  root,
  expanded,
  activePath,
  onToggle,
  onOpenDirectory,
  onOpenFile,
}: TreeNodeProps): React.ReactElement {
  const theme = useMantineTheme();
  const compact = useMediaQuery(`(min-width: ${theme.breakpoints.lg})`);
  const open = expanded.has(node.path);
  const active = activePath === node.path;
  const isDirectory = node.kind === "directory";
  const rowStyle = compact
    ? {
        minHeight: rem(28),
        paddingBottom: rem(3),
        paddingLeft: rem(8 + depth * 14),
        paddingRight: rem(8),
        paddingTop: rem(3),
      }
    : {
        minHeight: rem(34),
        paddingBottom: rem(6),
        paddingLeft: rem(10 + depth * 18),
        paddingRight: rem(10),
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
          borderLeft: `${rem(2)} solid ${
            active ? "var(--mantine-color-blue-6)" : "transparent"
          }`,
          color: active
            ? "var(--mantine-color-blue-7)"
            : "var(--mantine-color-text)",
          cursor: "pointer",
          ...rowStyle,
          minWidth: "100%",
          width: "max-content",
        }}
      >
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
          style={{ flexShrink: 0, whiteSpace: "nowrap" }}
        >
          {node.name}
        </Text>
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
              onToggle={onToggle}
              onOpenDirectory={onOpenDirectory}
              onOpenFile={onOpenFile}
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
  manifestEntries,
  entries,
  directoryEntriesByPath,
  selectedFilePath,
  isRefreshing,
  onOpenDirectory,
  onOpenFile,
  onRefresh,
}: FileBrowserProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const [query, setQuery] = useState("");
  const tree = useMemo(
    () => buildTree(cwd, manifestEntries, entries, directoryEntriesByPath),
    [cwd, directoryEntriesByPath, entries, manifestEntries],
  );
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([cwd]));

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
        <TextInput
          flex={1}
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
        <Tooltip label={t("expandAll")}>
          <ActionIcon size="sm" variant="subtle" onClick={handleExpandAll}>
            <IconChevronDown size="0.75rem" />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("collapseAll")}>
          <ActionIcon size="sm" variant="subtle" onClick={handleCollapseAll}>
            <IconChevronUp size="0.75rem" />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("refresh")}>
          <ActionIcon
            size="sm"
            variant="subtle"
            loading={isRefreshing}
            onClick={onRefresh}
          >
            <IconRefresh size="0.75rem" />
          </ActionIcon>
        </Tooltip>
      </Group>

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

      <ScrollArea flex={1} mih={0} type="auto" offsetScrollbars>
        <Box py={rem(4)}>
          {displayTree.length === 0 ? (
            <Text size="xs" c="dimmed" ta="center" py="xl">
              {query ? t("noSearchResults") : t("emptyDirectory")}
            </Text>
          ) : (
            displayTree.map((node) => (
              <TreeNode
                key={node.path}
                node={node}
                depth={0}
                root={root}
                expanded={effectiveExpanded}
                activePath={activePath}
                onToggle={handleToggle}
                onOpenDirectory={onOpenDirectory}
                onOpenFile={onOpenFile}
              />
            ))
          )}
        </Box>
      </ScrollArea>
    </Stack>
  );
}
