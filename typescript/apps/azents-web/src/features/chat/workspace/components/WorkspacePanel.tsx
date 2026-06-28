"use client";

/** Workspace panel shell component. */
import {
  Alert,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  rem,
  Stack,
  Tabs,
  Text,
} from "@mantine/core";
import { useModals } from "@mantine/modals";
import {
  IconAlertCircle,
  IconFolderOpen,
  IconPower,
  IconSettings,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { FileBrowser } from "./FileBrowser";
import { FileInfo } from "./FileInfo";
import { FileViewer } from "./FileViewer";
import { RuntimeActivationView } from "./RuntimeActivationView";
import type { WorkspacePanelState } from "../types";

type WorkspacePanelTab = "workspace" | "settings";

interface WorkspacePanelProps {
  state: WorkspacePanelState;
  defaultTab?: WorkspacePanelTab;
  onStartRuntime: () => void;
  onStopRuntime: () => void;
  onRestartRuntime: () => void;
  onResetRuntime: () => void;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onShowInfo: (path: string) => void;
  onBackToBrowser: () => void;
  onToggleSelectedPath: (path: string) => void;
  onClearSelection: () => void;
  onRefresh: () => void;
  onCreateDirectory: (path: string) => void;
  onRenamePath: (sourcePath: string, newName: string) => void;
  onMovePath: (sourcePath: string, destinationPath: string) => void;
  onDeletePath: (path: string, recursive: boolean) => void;
  onBulkMovePaths: (destinationDirectory: string) => void;
  onBulkDeletePaths: (recursive: boolean) => void;
  getDownloadHref: (path: string) => string;
}

export function WorkspacePanel({
  state,
  defaultTab = "workspace",
  onStartRuntime,
  onStopRuntime,
  onRestartRuntime,
  onResetRuntime,
  onOpenDirectory,
  onOpenFile,
  onShowInfo,
  onBackToBrowser,
  onToggleSelectedPath,
  onClearSelection,
  onRefresh,
  onCreateDirectory,
  onRenamePath,
  onMovePath,
  onDeletePath,
  onBulkMovePaths,
  onBulkDeletePaths,
  getDownloadHref,
}: WorkspacePanelProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const modals = useModals();
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const handleConfirmReset = (): void => {
    setResetConfirmOpen(false);
    onResetRuntime();
  };

  const openDeleteConfirm = (path: string, onConfirm: () => void): void => {
    modals.openConfirmModal({
      title: t("deleteConfirmTitle"),
      children: <Text size="sm">{t("deleteConfirm", { path })}</Text>,
      labels: { confirm: t("delete"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm,
    });
  };

  const openBulkDeleteConfirm = (
    count: number,
    onConfirm: () => void,
  ): void => {
    modals.openConfirmModal({
      title: t("bulkDeleteConfirmTitle"),
      children: <Text size="sm">{t("bulkDeleteConfirm", { count })}</Text>,
      labels: { confirm: t("delete"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm,
    });
  };

  const renderSettingsPanel = (): React.ReactElement => {
    if (state.type === "LOADING") {
      return (
        <Paper withBorder p="md" radius="lg">
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm">{t("loadingWorkspace")}</Text>
          </Group>
        </Paper>
      );
    }

    if (state.type === "ERROR") {
      return (
        <Alert color="red" icon={<IconAlertCircle size="1rem" />}>
          {state.message}
        </Alert>
      );
    }

    const { actions, runtime } = state.server;
    const canStopRuntime = actions.stop !== null;

    return (
      <Stack gap="md">
        <Paper withBorder p="md" radius="lg">
          <Stack gap="md">
            <Box>
              <Text size="lg" fw={700}>
                {t("settingsTitle")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("settingsSubtitle")}
              </Text>
            </Box>

            <Paper withBorder p="md" radius="md">
              <Group justify="space-between" align="center" gap="md">
                <Group gap="sm" miw={0} wrap="nowrap">
                  <Box c="red" style={{ display: "inline-flex" }}>
                    <IconPower size="1rem" />
                  </Box>
                  <Box miw={0}>
                    <Text size="sm" fw={600}>
                      {t("stopRuntime")}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {t("stopRuntimeDescription")}
                    </Text>
                  </Box>
                </Group>
                <Button
                  color="red"
                  variant="light"
                  loading={state.isStopping}
                  disabled={
                    !canStopRuntime || state.isStarting || state.isResetting
                  }
                  onClick={onStopRuntime}
                >
                  {state.isStopping ? t("stoppingRuntime") : t("stopRuntime")}
                </Button>
              </Group>
            </Paper>

            {!canStopRuntime && (
              <Text size="xs" c="dimmed">
                {runtime.type === "NOT_STARTED" || runtime.type === "HIBERNATED"
                  ? t("runtimeNotRunningHint")
                  : t("runtimeControlUnavailableHint")}
              </Text>
            )}
          </Stack>
        </Paper>
      </Stack>
    );
  };

  const renderWorkspacePanel = (): React.ReactElement => {
    if (state.type === "LOADING") {
      return (
        <Box flex={1} mih={0} w="100%" style={{ overflow: "hidden" }}>
          <Center h="100%">
            <Stack align="center" gap="sm">
              <Loader size="sm" />
              <Text size="sm" c="dimmed">
                {t("loadingWorkspace")}
              </Text>
            </Stack>
          </Center>
        </Box>
      );
    }
    if (state.type === "ERROR") {
      return (
        <Box flex={1} mih={0} w="100%" style={{ overflow: "hidden" }}>
          <Alert color="red" icon={<IconAlertCircle size="1rem" />}>
            {state.message}
          </Alert>
        </Box>
      );
    }

    const { runtime, workspace, actions } = state.server;
    const isTransitioning =
      runtime.type === "STARTING" ||
      runtime.type === "RESETTING" ||
      runtime.type === "STOPPING" ||
      workspace.type === "CONNECTING";
    const isInactive =
      runtime.type === "NOT_STARTED" || runtime.type === "HIBERNATED";
    const isRestoreFailed = runtime.type === "RESTORE_FAILED";
    const isRuntimeFailed = runtime.type === "LOST";
    const isControlUnavailable =
      workspace.type === "CONTROL_UNAVAILABLE" ||
      workspace.type === "READ_FAILED";

    return (
      <Box flex={1} mih={0} w="100%" style={{ overflow: "hidden" }}>
        {isTransitioning && (
          <Center h="100%" p="lg">
            <Stack align="center" gap="sm">
              <Loader size="sm" />
              <Text size="sm" c="dimmed" ta="center">
                {t("restoringRuntime")}
              </Text>
              {actions.stop && (
                <Button
                  size="xs"
                  variant="light"
                  color="gray"
                  loading={state.isStopping}
                  onClick={onStopRuntime}
                >
                  {state.isStopping ? t("stoppingRuntime") : t("stopRuntime")}
                </Button>
              )}
            </Stack>
          </Center>
        )}
        {!isTransitioning && isControlUnavailable && (
          <Center h="100%" p="lg">
            <Stack align="center" gap="md" maw={rem(420)}>
              <Alert
                color="red"
                icon={<IconAlertCircle size="1rem" />}
                title={t("controlUnavailableTitle")}
              >
                {workspace.detail}
              </Alert>
              <Stack align="center" gap="xs">
                <Group gap="xs">
                  <Button
                    variant="default"
                    onClick={onRefresh}
                    loading={state.isRefreshing}
                    disabled={state.isStopping || state.isResetting}
                  >
                    {t("refresh")}
                  </Button>
                  {actions.restart && (
                    <Button
                      onClick={onRestartRuntime}
                      loading={state.isStarting}
                      disabled={
                        state.isRefreshing ||
                        state.isStopping ||
                        state.isResetting
                      }
                    >
                      {t("restartRuntime")}
                    </Button>
                  )}
                  {actions.stop && (
                    <Button
                      onClick={onStopRuntime}
                      loading={state.isStopping}
                      disabled={
                        state.isRefreshing ||
                        state.isStarting ||
                        state.isResetting
                      }
                    >
                      {t("stopRuntime")}
                    </Button>
                  )}
                </Group>
                <Button
                  c="dimmed"
                  size="xs"
                  variant="transparent"
                  onClick={() => setResetConfirmOpen(true)}
                  loading={state.isResetting}
                  disabled={state.isRefreshing || state.isStopping}
                >
                  {t("resetRuntime")}
                </Button>
                <Modal
                  opened={resetConfirmOpen}
                  onClose={() => setResetConfirmOpen(false)}
                  title={t("resetRuntime")}
                  centered
                >
                  <Stack gap="md">
                    <Text size="sm">{t("resetRuntimeConfirm")}</Text>
                    <Group justify="flex-end">
                      <Button
                        variant="default"
                        onClick={() => setResetConfirmOpen(false)}
                      >
                        {t("cancel")}
                      </Button>
                      <Button
                        color="red"
                        onClick={handleConfirmReset}
                        loading={state.isResetting}
                      >
                        {t("resetRuntime")}
                      </Button>
                    </Group>
                  </Stack>
                </Modal>
              </Stack>
            </Stack>
          </Center>
        )}
        {!isTransitioning && !isControlUnavailable && isInactive && (
          <RuntimeActivationView
            canStartRuntime={actions.start !== null}
            isStarting={state.isStarting}
            onStartRuntime={onStartRuntime}
          />
        )}
        {!isTransitioning && !isControlUnavailable && isRestoreFailed && (
          <Center h="100%" p="lg">
            <Stack align="center" gap="md" maw={rem(420)}>
              <Alert
                color="red"
                icon={<IconAlertCircle size="1rem" />}
                title={t("restoreFailedTitle")}
              >
                {runtime.detail || t("restoreFailedDescription")}
              </Alert>
              {(actions.restart || actions.start) && (
                <Stack align="center" gap="xs">
                  <Button
                    onClick={
                      actions.restart ? onRestartRuntime : onStartRuntime
                    }
                    loading={state.isStarting}
                    disabled={state.isStarting || state.isResetting}
                  >
                    {actions.restart ? t("restartRuntime") : t("retryRestore")}
                  </Button>
                  <Button
                    c="dimmed"
                    size="xs"
                    variant="transparent"
                    onClick={() => setResetConfirmOpen(true)}
                    loading={state.isResetting}
                    disabled={state.isStarting || state.isResetting}
                  >
                    {t("resetRuntime")}
                  </Button>
                  <Modal
                    opened={resetConfirmOpen}
                    onClose={() => setResetConfirmOpen(false)}
                    title={t("resetRuntime")}
                    centered
                  >
                    <Stack gap="md">
                      <Text size="sm">{t("resetRuntimeConfirm")}</Text>
                      <Group justify="flex-end">
                        <Button
                          variant="default"
                          onClick={() => setResetConfirmOpen(false)}
                        >
                          {t("cancel")}
                        </Button>
                        <Button
                          color="red"
                          onClick={handleConfirmReset}
                          loading={state.isResetting}
                        >
                          {t("resetRuntime")}
                        </Button>
                      </Group>
                    </Stack>
                  </Modal>
                </Stack>
              )}
            </Stack>
          </Center>
        )}
        {!isTransitioning && !isControlUnavailable && isRuntimeFailed && (
          <Center h="100%" p="lg">
            <Stack align="center" gap="md" maw={rem(420)}>
              <Alert
                color="red"
                icon={<IconAlertCircle size="1rem" />}
                title={t("runtimeFailedTitle")}
              >
                {runtime.detail || t("runtimeFailedDescription")}
              </Alert>
              {(actions.restart || actions.start) && (
                <Button
                  onClick={actions.restart ? onRestartRuntime : onStartRuntime}
                  loading={state.isStarting}
                  disabled={state.isStarting || state.isResetting}
                >
                  {actions.restart ? t("restartRuntime") : t("startRuntime")}
                </Button>
              )}
            </Stack>
          </Center>
        )}
        {!isTransitioning &&
          !isControlUnavailable &&
          !isInactive &&
          !isRestoreFailed &&
          workspace.type === "UNAVAILABLE" && (
            <RuntimeActivationView
              canStartRuntime={actions.start !== null}
              isStarting={state.isStarting}
              onStartRuntime={onStartRuntime}
            />
          )}
        {!isTransitioning &&
          !isControlUnavailable &&
          !isInactive &&
          !isRestoreFailed &&
          workspace.type === "READY" &&
          state.manifest && (
            <Stack gap={0} h="100%" mih={0}>
              <Box flex={1} mih={0} style={{ overflow: "hidden" }}>
                {state.workspaceView === "preview" ? (
                  <FileViewer
                    state={state.fileState}
                    getDownloadHref={getDownloadHref}
                    onBack={onBackToBrowser}
                  />
                ) : state.workspaceView === "info" ? (
                  <FileInfo
                    entry={state.selectedEntry}
                    stat={
                      state.inspectorState.type === "LOADED"
                        ? state.inspectorState.stat
                        : null
                    }
                    isLoading={state.inspectorState.type === "LOADING"}
                    error={
                      state.inspectorState.type === "ERROR"
                        ? state.inspectorState.message
                        : null
                    }
                    getDownloadHref={getDownloadHref}
                    onBack={onBackToBrowser}
                    onCreateDirectory={() => {
                      const basePath =
                        state.selectedEntry?.kind === "directory"
                          ? state.selectedEntry.path
                          : state.directory.path;
                      const name = window.prompt(t("newFolderPrompt"));
                      if (name?.trim()) {
                        onCreateDirectory(`${basePath}/${name.trim()}`);
                      }
                    }}
                    onRename={(entry) => {
                      const name = window.prompt(t("renamePrompt"), entry.name);
                      if (name?.trim() && name.trim() !== entry.name) {
                        onRenamePath(entry.path, name.trim());
                      }
                    }}
                    onMove={(entry) => {
                      const destination = window.prompt(
                        t("movePrompt"),
                        entry.path,
                      );
                      if (
                        destination?.trim() &&
                        destination.trim() !== entry.path
                      ) {
                        onMovePath(entry.path, destination.trim());
                      }
                    }}
                    onDelete={(entry) =>
                      openDeleteConfirm(entry.path, () =>
                        onDeletePath(entry.path, entry.kind === "directory"),
                      )
                    }
                  />
                ) : (
                  <FileBrowser
                    root={state.manifest.root}
                    cwd={state.manifest.cwd}
                    path={state.directory.path}
                    manifestEntries={state.manifest.entries}
                    entries={state.directory.entries}
                    directoryEntriesByPath={state.directoryEntriesByPath}
                    selectedFilePath={state.selectedFilePath}
                    selectedPaths={state.selectedPaths}
                    isRefreshing={state.isRefreshing}
                    getDownloadHref={getDownloadHref}
                    onOpenDirectory={onOpenDirectory}
                    onOpenFile={onOpenFile}
                    onShowInfo={onShowInfo}
                    onToggleSelectedPath={onToggleSelectedPath}
                    onClearSelection={onClearSelection}
                    onBulkMove={() => {
                      const destination = window.prompt(
                        t("movePrompt"),
                        state.directory.path,
                      );
                      if (destination?.trim()) {
                        onBulkMovePaths(destination.trim());
                      }
                    }}
                    onBulkDelete={() =>
                      openBulkDeleteConfirm(state.selectedPaths.length, () =>
                        onBulkDeletePaths(true),
                      )
                    }
                    onCreateDirectory={(basePath) => {
                      const name = window.prompt(t("newFolderPrompt"));
                      if (name?.trim()) {
                        onCreateDirectory(`${basePath}/${name.trim()}`);
                      }
                    }}
                    onRenamePath={(entry) => {
                      const name = window.prompt(t("renamePrompt"), entry.name);
                      if (name?.trim() && name.trim() !== entry.name) {
                        onRenamePath(entry.path, name.trim());
                      }
                    }}
                    onMovePath={(entry) => {
                      const destination = window.prompt(
                        t("movePrompt"),
                        entry.path,
                      );
                      if (
                        destination?.trim() &&
                        destination.trim() !== entry.path
                      ) {
                        onMovePath(entry.path, destination.trim());
                      }
                    }}
                    onDeletePath={(entry) =>
                      openDeleteConfirm(entry.path, () =>
                        onDeletePath(entry.path, entry.kind === "directory"),
                      )
                    }
                    onRefresh={onRefresh}
                  />
                )}
              </Box>
            </Stack>
          )}
      </Box>
    );
  };

  return (
    <Tabs
      defaultValue={defaultTab}
      keepMounted={false}
      h="100%"
      style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}
    >
      <Tabs.List grow style={{ flexShrink: 0 }}>
        <Tabs.Tab
          value="workspace"
          leftSection={<IconFolderOpen size="1rem" />}
        >
          {t("workspaceTab")}
        </Tabs.Tab>
        <Tabs.Tab value="settings" leftSection={<IconSettings size="1rem" />}>
          {t("settingsTab")}
        </Tabs.Tab>
      </Tabs.List>

      <Tabs.Panel
        value="workspace"
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {renderWorkspacePanel()}
      </Tabs.Panel>
      <Tabs.Panel
        value="settings"
        p="md"
        style={{ flex: 1, minHeight: 0, overflow: "auto" }}
      >
        {renderSettingsPanel()}
      </Tabs.Panel>
    </Tabs>
  );
}
