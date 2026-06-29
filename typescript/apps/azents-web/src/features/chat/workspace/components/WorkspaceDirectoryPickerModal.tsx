"use client";

/** Runtime-backed directory picker for selecting Project roots. */

import {
  ActionIcon,
  Alert,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconFolder, IconFolderPlus, IconRefresh } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type {
  AgentWorkspaceEntryResponse,
  AgentWorkspaceResponse,
} from "@azents/public-client";

export type ProjectDirectoryPickerState =
  | { type: "CLOSED" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "SERVER";
      server: AgentWorkspaceResponse;
      currentPath: string;
      entries: AgentWorkspaceEntryResponse[];
      isRefreshing: boolean;
      isStarting: boolean;
    };

export interface WorkspaceDirectoryPickerModalProps {
  opened: boolean;
  state: ProjectDirectoryPickerState;
  onClose: () => void;
  onOpenDirectory: (path: string) => void;
  onSelectCurrentDirectory: () => void;
  onRefresh: () => void;
  onStartRuntime: () => void;
}

function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1) || trimmed;
}

function parentPath(path: string): string | null {
  const trimmed = path.replace(/\/+$/, "");
  const index = trimmed.lastIndexOf("/");
  if (index <= 0) {
    return null;
  }
  return trimmed.slice(0, index);
}

export function WorkspaceDirectoryPickerModal({
  opened,
  state,
  onClose,
  onOpenDirectory,
  onSelectCurrentDirectory,
  onRefresh,
  onStartRuntime,
}: WorkspaceDirectoryPickerModalProps): React.ReactElement {
  const t = useTranslations("chat");

  const renderServerContent = (): React.ReactElement | null => {
    if (state.type !== "SERVER") {
      return null;
    }

    const { runtime, workspace } = state.server;
    const isTransitioning =
      runtime.type === "STARTING" ||
      runtime.type === "RESETTING" ||
      runtime.type === "STOPPING" ||
      workspace.type === "CONNECTING";

    if (isTransitioning) {
      return (
        <Center py="xl">
          <Stack align="center" gap="xs">
            <Loader size="sm" />
            <Text c="dimmed" size="sm" ta="center">
              {t("workspacePanel.restoringRuntime")}
            </Text>
            <Button
              loading={state.isRefreshing}
              size="xs"
              variant="subtle"
              onClick={onRefresh}
            >
              {t("workspacePanel.refresh")}
            </Button>
          </Stack>
        </Center>
      );
    }

    if (
      workspace.type === "CONTROL_UNAVAILABLE" ||
      workspace.type === "READ_FAILED"
    ) {
      return (
        <Alert color="red" title={t("workspacePanel.controlUnavailableTitle")}>
          <Stack gap="xs">
            <Text size="sm">{workspace.detail}</Text>
            <Group gap="xs">
              <Button
                loading={state.isRefreshing}
                size="xs"
                variant="default"
                onClick={onRefresh}
              >
                {t("workspacePanel.refresh")}
              </Button>
              <Button
                loading={state.isStarting}
                size="xs"
                onClick={onStartRuntime}
              >
                {t("workspacePanel.restartRuntime")}
              </Button>
            </Group>
          </Stack>
        </Alert>
      );
    }

    if (workspace.type !== "READY") {
      return (
        <Alert color="blue" title={t("workspacePanel.inactiveTitle")}>
          <Stack gap="xs">
            <Text size="sm">{t("workspacePanel.inactiveDescription")}</Text>
            <Group gap="xs">
              <Button
                loading={state.isStarting}
                size="xs"
                onClick={onStartRuntime}
              >
                {t("projectPickerStartRuntime")}
              </Button>
              <Button size="xs" variant="subtle" onClick={onRefresh}>
                {t("workspacePanel.refresh")}
              </Button>
            </Group>
          </Stack>
        </Alert>
      );
    }

    const directoryEntries = state.entries.filter(
      (entry) => entry.kind === "directory",
    );
    const workspaceRoot = workspace.manifest.root;
    const rawParent = parentPath(state.currentPath);
    const parent =
      rawParent &&
      (rawParent === workspaceRoot || rawParent.startsWith(`${workspaceRoot}/`))
        ? rawParent
        : null;
    const canSelectCurrent =
      state.currentPath !== "" && state.currentPath !== workspaceRoot;

    return (
      <Stack gap="sm">
        <Group justify="space-between" gap="sm">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text c="dimmed" size="xs">
              {t("projectPickerCurrentPath")}
            </Text>
            <Text fw={500} size="sm" truncate>
              {state.currentPath}
            </Text>
          </Stack>
          <Group gap="xs">
            <Tooltip label={t("workspacePanel.refresh")}>
              <ActionIcon
                aria-label={t("workspacePanel.refresh")}
                loading={state.isRefreshing}
                variant="subtle"
                onClick={onRefresh}
              >
                <IconRefresh size={16} />
              </ActionIcon>
            </Tooltip>
            <Button
              disabled={!canSelectCurrent}
              leftSection={<IconFolderPlus size={16} />}
              size="xs"
              onClick={onSelectCurrentDirectory}
            >
              {t("projectPickerSelectCurrent")}
            </Button>
          </Group>
        </Group>
        <ScrollArea.Autosize mah={360} type="auto">
          <Stack gap={6}>
            {parent ? (
              <Button
                justify="flex-start"
                variant="subtle"
                onClick={() => onOpenDirectory(parent)}
              >
                ../
              </Button>
            ) : null}
            {directoryEntries.map((entry) => (
              <Paper key={entry.path} withBorder p="xs" radius="md">
                <Group justify="space-between" wrap="nowrap">
                  <Group gap="xs" style={{ minWidth: 0 }}>
                    <IconFolder size={18} />
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text size="sm" truncate>
                        {basename(entry.path)}
                      </Text>
                      <Text c="dimmed" size="xs" truncate>
                        {entry.path}
                      </Text>
                    </Stack>
                  </Group>
                  <Button
                    size="compact-xs"
                    variant="light"
                    onClick={() => onOpenDirectory(entry.path)}
                  >
                    {t("projectPickerOpenDirectory")}
                  </Button>
                </Group>
              </Paper>
            ))}
            {directoryEntries.length === 0 ? (
              <Text c="dimmed" py="lg" size="sm" ta="center">
                {t("projectPickerNoDirectories")}
              </Text>
            ) : null}
          </Stack>
        </ScrollArea.Autosize>
      </Stack>
    );
  };

  return (
    <Modal
      centered
      opened={opened}
      size="lg"
      title={t("projectPickerTitle")}
      onClose={onClose}
    >
      <Stack gap="sm">
        <Text c="dimmed" size="sm">
          {t("projectPickerDescription")}
        </Text>
        {state.type === "LOADING" ? (
          <Center py="xl">
            <Loader size="sm" />
          </Center>
        ) : null}
        {state.type === "ERROR" ? (
          <Alert color="red">{state.message}</Alert>
        ) : null}
        {renderServerContent()}
      </Stack>
    </Modal>
  );
}
