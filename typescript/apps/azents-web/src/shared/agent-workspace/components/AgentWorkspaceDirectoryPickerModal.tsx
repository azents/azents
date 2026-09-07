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
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import {
  IconBrandGit,
  IconFolder,
  IconFolderPlus,
  IconRefresh,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import { RuntimeLifecycleStatus } from "@/shared/components/runtime/RuntimeLifecycleStatus";
import classes from "./AgentWorkspaceDirectoryPickerModal.module.css";
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
  onRestartRuntime: () => void;
  runtimeSettingsHref?: string;
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
  onRestartRuntime,
  runtimeSettingsHref,
  translationNamespace = "agentWorkspacePicker",
}: AgentWorkspaceDirectoryPickerModalProps): React.ReactElement {
  const t = useTranslations(translationNamespace);
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);

  const closePicker = (): void => {
    setRestartConfirmOpen(false);
    onClose();
  };

  const renderStatusViewport = (
    content: React.ReactNode,
  ): React.ReactElement => (
    <div className={classes.statusViewport}>{content}</div>
  );

  const renderCapabilityContent = (): React.ReactElement | null => {
    if (state.type === "RUNTIME_FREE") {
      return renderStatusViewport(
        <Alert color="blue" title={t("workspacePanel.runtimeFreeTitle")}>
          <Stack gap="sm">
            <Text size="sm">{t("workspacePanel.runtimeFreeDescription")}</Text>
            {state.runtime.actions.add && runtimeSettingsHref ? (
              <Button
                component={Link}
                href={runtimeSettingsHref}
                size="xs"
                onClick={closePicker}
              >
                {t("workspacePanel.addRuntime")}
              </Button>
            ) : null}
          </Stack>
        </Alert>,
      );
    }
    if (state.type === "REMOVING") {
      return renderStatusViewport(
        <Alert color="yellow" title={t("workspacePanel.removingTitle")}>
          {t("workspacePanel.removingDescription")}
        </Alert>,
      );
    }
    return null;
  };

  const renderServerContent = (): React.ReactElement | null => {
    if (state.type !== "SERVER") {
      return null;
    }

    const { lifecycle, workspace } = state.server;
    const lifecycleStatus = lifecycle ? (
      <RuntimeLifecycleStatus lifecycle={lifecycle} compact />
    ) : null;
    const isTransitioning =
      lifecycle?.availability === "transitioning" ||
      (lifecycle === null && workspace.type === "CONNECTING");

    if (isTransitioning) {
      return renderStatusViewport(
        <Stack gap="md">
          {lifecycleStatus}
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
        </Stack>,
      );
    }

    if (
      workspace.type === "CONTROL_UNAVAILABLE" ||
      workspace.type === "READ_FAILED"
    ) {
      return renderStatusViewport(
        <Stack gap="md">
          {lifecycleStatus}
          <Alert
            color="red"
            title={t("workspacePanel.controlUnavailableTitle")}
          >
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
                {state.server.actions.restart ? (
                  <Button
                    loading={state.isRestarting}
                    size="xs"
                    onClick={() => setRestartConfirmOpen(true)}
                  >
                    {t("workspacePanel.restartRuntime")}
                  </Button>
                ) : null}
              </Group>
            </Stack>
          </Alert>
        </Stack>,
      );
    }

    if (workspace.type !== "READY") {
      return renderStatusViewport(
        <Stack gap="md">
          {lifecycleStatus}
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
        </Stack>,
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
      <section
        aria-label={t("projectPickerTitle")}
        className={classes.directoryBrowser}
      >
        <header
          className={classes.directoryToolbar}
          data-testid="agent-workspace-picker-toolbar"
        >
          <Stack className={classes.currentPath} gap="xs">
            <Text c="dimmed" size="xs">
              {t("projectPickerCurrentPath")}
            </Text>
            <Text fw={500} size="sm" truncate>
              {state.currentPath}
            </Text>
          </Stack>
          <Group className={classes.directoryActions} gap="xs" wrap="nowrap">
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
        </header>
        <div
          aria-label={t("projectPickerTitle")}
          className={classes.directoryList}
          data-testid="agent-workspace-picker-directory-list"
          tabIndex={0}
        >
          <div className={classes.directoryItems}>
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
                className={classes.directoryRow}
                withBorder
                px="sm"
                py="xs"
                radius="sm"
              >
                <UnstyledButton
                  className={classes.directoryOpenButton}
                  data-testid={`agent-workspace-picker-directory-${entry.path}`}
                  onClick={() => onOpenDirectory(entry.path)}
                >
                  {entry.repositoryType === "git" ? (
                    <IconBrandGit
                      className={classes.directoryIcon}
                      color="var(--mantine-color-grape-6)"
                      size={rem(16)}
                    />
                  ) : (
                    <IconFolder
                      className={classes.directoryIcon}
                      size={rem(16)}
                    />
                  )}
                  <Text
                    className={classes.directoryName}
                    fw={500}
                    size="sm"
                    truncate
                  >
                    {basename(entry.path)}
                  </Text>
                </UnstyledButton>
                <Tooltip label={t("projectPickerSelectDirectory")}>
                  <ActionIcon
                    data-testid={`agent-workspace-picker-select-${entry.path}`}
                    aria-label={t("projectPickerSelectDirectory")}
                    className={classes.directorySelectButton}
                    size={rem(30)}
                    variant="light"
                    onClick={() => onSelectDirectory(entry)}
                  >
                    <IconFolderPlus size={rem(15)} />
                  </ActionIcon>
                </Tooltip>
              </Paper>
            ))}
            {directoryEntries.length === 0 ? (
              <Text c="dimmed" py="lg" size="sm" ta="center">
                {t("projectPickerNoDirectories")}
              </Text>
            ) : null}
          </div>
        </div>
      </section>
    );
  };

  const renderPickerContent = (): React.ReactElement | null => {
    if (state.type === "LOADING") {
      return renderStatusViewport(
        <Center py="xl">
          <Loader size="sm" />
        </Center>,
      );
    }
    if (state.type === "ERROR") {
      return renderStatusViewport(<Alert color="red">{state.message}</Alert>);
    }
    return renderCapabilityContent() ?? renderServerContent();
  };

  return (
    <>
      <Modal
        centered
        data-testid="agent-workspace-directory-picker"
        opened={opened}
        size="lg"
        title={t("projectPickerTitle")}
        classNames={{
          body: classes.modalBody,
          content: classes.modalContent,
        }}
        onClose={closePicker}
      >
        <div className={classes.pickerLayout}>
          <Text c="dimmed" size="sm">
            {t("projectPickerDescription")}
          </Text>
          <div className={classes.stateSlot}>{renderPickerContent()}</div>
        </div>
      </Modal>
      <Modal
        centered
        opened={opened && restartConfirmOpen}
        title={t("workspacePanel.restartConfirmTitle")}
        onClose={() => setRestartConfirmOpen(false)}
      >
        <Stack gap="md">
          <Text size="sm">{t("workspacePanel.restartConfirmDescription")}</Text>
          <Alert color="blue">
            {t("workspacePanel.restartPreservationNotice")}
          </Alert>
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setRestartConfirmOpen(false)}
            >
              {t("workspacePanel.cancel")}
            </Button>
            <Button
              loading={state.type === "SERVER" ? state.isRestarting : false}
              onClick={() => {
                setRestartConfirmOpen(false);
                onRestartRuntime();
              }}
            >
              {t("workspacePanel.confirmRestart")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
