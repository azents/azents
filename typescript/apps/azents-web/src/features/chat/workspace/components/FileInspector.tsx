"use client";

/** Agent Workspace file inspector component. */
import {
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconDownload,
  IconEdit,
  IconFolderPlus,
  IconInfoCircle,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { WorkspaceEntry, WorkspacePathStat } from "../types";

interface FileInspectorProps {
  entry: WorkspaceEntry | null;
  stat: WorkspacePathStat | null;
  isLoading: boolean;
  error: string | null;
  getDownloadHref: (path: string) => string;
  onCreateDirectory: () => void;
  onRename: (entry: WorkspaceEntry) => void;
  onMove: (entry: WorkspaceEntry) => void;
  onDelete: (entry: WorkspaceEntry) => void;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) {
    return "—";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string | null): string {
  if (value === null) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function MetadataRow({
  label,
  value,
}: {
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <Group justify="space-between" gap="sm" wrap="nowrap">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xs" ff="monospace" ta="right" truncate>
        {value}
      </Text>
    </Group>
  );
}

export function FileInspector({
  entry,
  stat,
  isLoading,
  error,
  getDownloadHref,
  onCreateDirectory,
  onRename,
  onMove,
  onDelete,
}: FileInspectorProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  return (
    <Paper
      withBorder
      radius={0}
      p="sm"
      style={{ borderLeft: 0, borderRight: 0, borderBottom: 0 }}
    >
      <Stack gap="xs">
        <Group gap="xs" wrap="nowrap">
          <IconInfoCircle size="0.875rem" />
          <Text size="sm" fw={600}>
            {t("inspector")}
          </Text>
        </Group>
        {entry === null ? (
          <Text size="xs" c="dimmed">
            {t("selectFile")}
          </Text>
        ) : (
          <>
            <Group gap="xs" wrap="nowrap">
              <Button
                size="xs"
                variant="light"
                leftSection={<IconFolderPlus size="0.875rem" />}
                onClick={onCreateDirectory}
              >
                {t("newFolder")}
              </Button>
              {entry.kind === "file" && (
                <Button
                  component="a"
                  href={getDownloadHref(entry.path)}
                  size="xs"
                  variant="subtle"
                  leftSection={<IconDownload size="0.875rem" />}
                >
                  {t("download")}
                </Button>
              )}
              <Button
                size="xs"
                variant="subtle"
                leftSection={<IconEdit size="0.875rem" />}
                onClick={() => onRename(entry)}
              >
                {t("rename")}
              </Button>
              <Button size="xs" variant="subtle" onClick={() => onMove(entry)}>
                {t("move")}
              </Button>
              <Button
                size="xs"
                variant="subtle"
                color="red"
                leftSection={<IconTrash size="0.875rem" />}
                onClick={() => onDelete(entry)}
              >
                {t("delete")}
              </Button>
            </Group>
            <Divider />
            {isLoading ? (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="xs" c="dimmed">
                  {t("loadingInspector")}
                </Text>
              </Group>
            ) : error !== null ? (
              <Text size="xs" c="red">
                {error}
              </Text>
            ) : (
              <Stack gap={rem(4)}>
                <MetadataRow
                  label={t("name")}
                  value={stat?.name ?? entry.name}
                />
                <MetadataRow
                  label={t("type")}
                  value={stat?.kind ?? entry.kind}
                />
                <MetadataRow label={t("pathLabel")} value={entry.path} />
                <MetadataRow
                  label={t("size")}
                  value={formatFileSize(stat?.size ?? entry.size)}
                />
                <MetadataRow
                  label={t("mediaType")}
                  value={stat?.mediaType ?? entry.mediaType ?? "—"}
                />
                <MetadataRow
                  label={t("modifiedAt")}
                  value={formatDate(stat?.modifiedAt ?? entry.modifiedAt)}
                />
                <MetadataRow
                  label={t("symlink")}
                  value={stat?.symlink === true ? t("yes") : t("no")}
                />
                {stat?.realPath ? (
                  <MetadataRow label={t("realPath")} value={stat.realPath} />
                ) : null}
                {stat?.resolvedKind ? (
                  <MetadataRow
                    label={t("resolvedKind")}
                    value={stat.resolvedKind}
                  />
                ) : null}
              </Stack>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );
}
