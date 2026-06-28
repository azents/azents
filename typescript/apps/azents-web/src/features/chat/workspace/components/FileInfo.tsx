"use client";

/** Agent Workspace file information page component. */
import {
  Alert,
  Button,
  Divider,
  Group,
  Loader,
  Menu,
  Paper,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconDotsVertical,
  IconDownload,
  IconEdit,
  IconFolderPlus,
  IconInfoCircle,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { WorkspaceEntry, WorkspacePathStat } from "../types";

interface FileInfoProps {
  entry: WorkspaceEntry | null;
  stat: WorkspacePathStat | null;
  isLoading: boolean;
  error: string | null;
  getDownloadHref: (path: string) => string;
  onBack: () => void;
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
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text size="sm" ff="monospace" ta="right" truncate>
        {value}
      </Text>
    </Group>
  );
}

export function FileInfo({
  entry,
  stat,
  isLoading,
  error,
  getDownloadHref,
  onBack,
  onCreateDirectory,
  onRename,
  onMove,
  onDelete,
}: FileInfoProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  if (entry === null) {
    return (
      <Stack gap="md" p="md">
        <Button variant="subtle" onClick={onBack} w="fit-content">
          {t("backToBrowser")}
        </Button>
        <Text size="sm" c="dimmed">
          {t("selectFileForInfo")}
        </Text>
      </Stack>
    );
  }

  return (
    <Stack gap="md" p="md" h="100%" mih={0} style={{ overflow: "auto" }}>
      <Group justify="space-between" align="center" wrap="nowrap">
        <Group gap="xs" miw={0} wrap="nowrap">
          <IconInfoCircle size="1rem" />
          <Text size="md" fw={700} truncate>
            {t("fileInfo")}
          </Text>
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Button size="xs" variant="subtle" onClick={onBack}>
            {t("backToBrowser")}
          </Button>
          <Menu withinPortal position="bottom-end">
            <Menu.Target>
              <Button
                size="xs"
                variant="light"
                rightSection={<IconDotsVertical size="0.875rem" />}
              >
                {t("actions")}
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                leftSection={<IconFolderPlus size="0.875rem" />}
                onClick={onCreateDirectory}
              >
                {t("newFolder")}
              </Menu.Item>
              {entry.kind === "file" && (
                <Menu.Item
                  component="a"
                  href={getDownloadHref(entry.path)}
                  leftSection={<IconDownload size="0.875rem" />}
                >
                  {t("download")}
                </Menu.Item>
              )}
              <Menu.Item
                leftSection={<IconEdit size="0.875rem" />}
                onClick={() => onRename(entry)}
              >
                {t("rename")}
              </Menu.Item>
              <Menu.Item onClick={() => onMove(entry)}>{t("move")}</Menu.Item>
              <Menu.Divider />
              <Menu.Item
                color="red"
                leftSection={<IconTrash size="0.875rem" />}
                onClick={() => onDelete(entry)}
              >
                {t("delete")}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </Group>

      <Paper withBorder radius="md" p="md">
        {isLoading ? (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              {t("loadingFileInfo")}
            </Text>
          </Group>
        ) : error !== null ? (
          <Alert color="red">{error}</Alert>
        ) : (
          <Stack gap={rem(8)}>
            <MetadataRow label={t("name")} value={stat?.name ?? entry.name} />
            <MetadataRow label={t("type")} value={stat?.kind ?? entry.kind} />
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
      </Paper>
      <Divider />
    </Stack>
  );
}
