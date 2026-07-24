"use client";

/** Runtime-backed existing-directory picker shared by Agent workspace surfaces. */

import {
  ActionIcon,
  Alert,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconBrandGit,
  IconFolder,
  IconFolderPlus,
  IconRefresh,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type {
  ProjectDirectoryPickerEntry,
  ProjectDirectoryPickerState,
} from "../types";

export interface AgentWorkspaceDirectoryPickerModalProps {
  opened: boolean;
  state: ProjectDirectoryPickerState;
  onClose: () => void;
  onOpenDirectory: (path: string) => void;
  onSelectDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  onRefresh: () => void;
  onStartRuntime: () => void;
  translationNamespace?: "chat" | "agentWorkspacePicker";
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

export function AgentWorkspaceDirectoryPickerModal({
  opened,
  state,
  onClose,
  onOpenDirectory,
  onSelectDirectory,
  onRefresh,
  onStartRuntime,
  translationNamespace = "agentWorkspacePicker",
}: AgentWorkspaceDirectoryPickerModalProps): React.ReactElement {
  const t = useTranslations(translationNamespace);

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
    const currentEntry: ProjectDirectoryPickerEntry = {
      path: state.currentPath,
      kind: "directory",
      repositoryType:
        directoryEntries.find((entry) => entry.path === state.currentPath)
          ?.repositoryType ?? null,
    };
    const workspaceRoot = workspace.manifest.root;
    const rawParent = parentPath(state.currentPath);
    const parent =
      rawParent &&
      (rawParent === workspaceRoot || rawParent.startsWith(`${workspaceRoot}/`))
        ? rawParent
        : null;

    return (
      <Stack gap="sm">
        <Group justify="space-between" gap="sm" wrap="nowrap">
          <Stack gap="xs" style={{ minWidth: 0, flex: 1 }}>
            <Text c="dimmed" size="xs">
              {t("projectPickerCurrentPath")}
            </Text>
            <Text fw={500} size="sm" truncate>
              {state.currentPath}
            </Text>
          </Stack>
          <Group gap="xs">
            <Button
              disabled={state.currentPath === workspaceRoot}
              leftSection={<IconFolderPlus size={rem(16)} />}
              size="xs"
              variant="light"
              onClick={() => onSelectDirectory(currentEntry)}
            >
              {t("projectPickerSelectCurrent")}
            </Button>
            <Tooltip label={t("workspacePanel.refresh")}>
              <ActionIcon
                aria-label={t("workspacePanel.refresh")}
                loading={state.isRefreshing}
                variant="subtle"
                onClick={onRefresh}
              >
                <IconRefresh size={rem(16)} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
        <ScrollArea.Autosize mah={{ base: rem(520), sm: rem(440) }} type="auto">
          <Stack gap="xs" style={{ minWidth: 0, width: "100%" }}>
            {parent ? (
              <Button
                fullWidth
                justify="flex-start"
                size="compact-sm"
                variant="subtle"
                onClick={() => onOpenDirectory(parent)}
              >
                ../
              </Button>
            ) : null}
            {directoryEntries.map((entry) => (
              <Paper
                key={entry.path}
                data-testid={`agent-workspace-picker-directory-${entry.path}`}
                withBorder
                px="sm"
                py="xs"
                radius="sm"
                style={{
                  boxSizing: "border-box",
                  cursor: "pointer",
                  maxWidth: "100%",
                  minWidth: 0,
                  width: "100%",
                }}
                onClick={() => onOpenDirectory(entry.path)}
              >
                <Group
                  justify="space-between"
                  wrap="nowrap"
                  gap="xs"
                  style={{ maxWidth: "100%", minWidth: 0, width: "100%" }}
                >
                  <Group
                    gap="sm"
                    style={{ flex: "1 1 auto", minWidth: 0 }}
                    wrap="nowrap"
                  >
                    {entry.repositoryType === "git" ? (
                      <IconBrandGit
                        color="var(--mantine-color-grape-6)"
                        size={rem(16)}
                        style={{ flex: "0 0 auto" }}
                      />
                    ) : (
                      <IconFolder size={rem(16)} style={{ flex: "0 0 auto" }} />
                    )}
                    <Text fw={500} size="sm" truncate style={{ minWidth: 0 }}>
                      {basename(entry.path)}
                    </Text>
                  </Group>
                  <Tooltip label={t("projectPickerSelectDirectory")}>
                    <ActionIcon
                      data-testid={`agent-workspace-picker-select-${entry.path}`}
                      aria-label={t("projectPickerSelectDirectory")}
                      size={rem(30)}
                      style={{ flex: "0 0 auto" }}
                      variant="light"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelectDirectory(entry);
                      }}
                    >
                      <IconFolderPlus size={rem(15)} />
                    </ActionIcon>
                  </Tooltip>
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
      data-testid="agent-workspace-directory-picker"
      opened={opened}
      size="lg"
      title={t("projectPickerTitle")}
      styles={{
        body: { overflowX: "hidden" },
        content: { overflowX: "hidden" },
      }}
      onClose={onClose}
    >
      <Stack gap="sm" style={{ minWidth: 0, overflowX: "hidden" }}>
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
