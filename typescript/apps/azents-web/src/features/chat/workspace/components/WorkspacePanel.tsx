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
  Select,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { useModals } from "@mantine/modals";
import {
  IconAlertCircle,
  IconBrandGit,
  IconChartHistogram,
  IconFolderOpen,
  IconPlayerPlay,
  IconPower,
  IconRefresh,
  IconSettings,
  IconTerminal2,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { RuntimeLifecycleStatus } from "@/shared/components/runtime/RuntimeLifecycleStatus";
import { RuntimeSystemMetricsOverview } from "@/shared/runtime-metrics/components/RuntimeSystemMetricsOverview";
import { FileBrowser } from "./FileBrowser";
import { FileInfo } from "./FileInfo";
import { FileViewer } from "./FileViewer";
import { RuntimeActivationView } from "./RuntimeActivationView";
import { RuntimeConfigurationStatus } from "./RuntimeConfigurationStatus";
import { WorkspaceDirectoryPickerModal } from "./WorkspaceDirectoryPickerModal";
import type {
  ProjectRegistrationDialogState,
  ProjectRegistrationMode,
  WorkspaceBrowserMode,
  WorkspaceEntry,
  WorkspacePanelState,
  WorkspacePanelTab,
  WorkspaceProjectPanelState,
} from "../types";
import type {
  ProjectDirectoryPickerEntry,
  ProjectDirectoryPickerState,
} from "./WorkspaceDirectoryPickerModal";
import type { RuntimeSystemMetricsOverviewState } from "@/shared/runtime-metrics/types";

const closedProjectRegistrationDialog: ProjectRegistrationDialogState = {
  type: "CLOSED",
};

interface WorkspacePanelProps {
  state: WorkspacePanelState;
  projectState: WorkspaceProjectPanelState;
  metricsState: RuntimeSystemMetricsOverviewState;
  defaultTab?: WorkspacePanelTab;
  activeTab?: WorkspacePanelTab;
  restartConfirmOpen?: boolean;
  resetConfirmOpen?: boolean;
  onSetActiveTab?: (tab: WorkspacePanelTab) => void;
  onOpenRestartConfirm?: () => void;
  onCloseRestartConfirm?: () => void;
  onConfirmRestart?: () => void;
  onOpenResetConfirm?: () => void;
  onCloseResetConfirm?: () => void;
  onConfirmReset?: () => void;
  fileBrowserQuery?: string;
  expandedFileNodeIds?: Set<string>;
  onSetFileBrowserQuery?: (query: string) => void;
  onSetExpandedFileNodeIds?: (nodeIds: Set<string>) => void;
  runtimeSettingsHref: string;
  onStartRuntime: () => void;
  onStopRuntime: () => void;
  onRestartRuntime?: () => void;
  onResetRuntime?: () => void;
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
  projectPickerState: ProjectDirectoryPickerState;
  isProjectPickerOpen: boolean;
  onOpenProjectPicker: () => void;
  onCloseProjectPicker: () => void;
  onOpenProjectPickerDirectory: (path: string) => void;
  onSelectProjectPickerDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  onRefreshProjectPicker: () => void;
  onStartRuntimeForProjectPicker: () => void;
  onRestartRuntimeForProjectPicker: () => void;
  onCloseProjectRegistration: () => void;
  onSetProjectRegistrationMode: (mode: ProjectRegistrationMode) => void;
  onSetProjectRegistrationStartingRef: (ref: string | null) => void;
  onSubmitProjectRegistration: () => void;
  onRemoveProjectEntry: (entry: WorkspaceEntry) => void;
  onDeleteWorktreeProjectEntry: (entry: WorkspaceEntry) => void;
  onSetBrowserMode: (mode: WorkspaceBrowserMode) => void;
}

export function WorkspacePanel({
  state,
  projectState,
  metricsState,
  defaultTab = "workspace",
  activeTab = defaultTab,
  restartConfirmOpen = false,
  resetConfirmOpen = false,
  onSetActiveTab = (): void => {},
  onOpenRestartConfirm = (): void => {},
  onCloseRestartConfirm = (): void => {},
  onConfirmRestart = (): void => {},
  onOpenResetConfirm = (): void => {},
  onCloseResetConfirm = (): void => {},
  onConfirmReset = (): void => {},
  fileBrowserQuery = "",
  expandedFileNodeIds = new Set<string>(),
  onSetFileBrowserQuery = (): void => {},
  onSetExpandedFileNodeIds = (): void => {},
  runtimeSettingsHref,
  onStartRuntime,
  onStopRuntime,
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
  projectPickerState,
  isProjectPickerOpen,
  onOpenProjectPicker,
  onCloseProjectPicker,
  onOpenProjectPickerDirectory,
  onSelectProjectPickerDirectory,
  onRefreshProjectPicker,
  onStartRuntimeForProjectPicker,
  onRestartRuntimeForProjectPicker,
  onCloseProjectRegistration,
  onSetProjectRegistrationMode,
  onSetProjectRegistrationStartingRef,
  onSubmitProjectRegistration,
  onRemoveProjectEntry,
  onDeleteWorktreeProjectEntry,
  onSetBrowserMode,
}: WorkspacePanelProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const modals = useModals();
  const metricsTabAvailable =
    state.type === "SERVER" || state.type === "REMOVING";
  const resolvedActiveTab =
    activeTab === "metrics" && !metricsTabAvailable ? "workspace" : activeTab;
  const registrationDialog =
    projectState.type === "READY"
      ? projectState.registrationDialog
      : closedProjectRegistrationDialog;
  const basename = (path: string): string => {
    const trimmed = path.replace(/\/+$/, "");
    return trimmed.slice(trimmed.lastIndexOf("/") + 1) || trimmed;
  };
  const gitRefOptions =
    registrationDialog.type === "OPEN" &&
    registrationDialog.gitRefPreview.type === "READY"
      ? registrationDialog.gitRefPreview.refs.map((ref) => ({
          value: ref.ref,
          label: ref.default ? `${ref.name} (${t("defaultRef")})` : ref.name,
        }))
      : [];
  const worktreeSubmitDisabled =
    registrationDialog.type === "OPEN" &&
    registrationDialog.mode === "git_worktree" &&
    (registrationDialog.gitRefPreview.type !== "READY" ||
      registrationDialog.startingRef === null);

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

  const openRemoveProjectConfirm = (entry: WorkspaceEntry): void => {
    modals.openConfirmModal({
      title: t("deleteProjectConfirmTitle"),
      children: (
        <Text size="sm">
          {t("deleteProjectConfirmDescription", { path: entry.path })}
        </Text>
      ),
      labels: { confirm: t("deleteProject"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () => onRemoveProjectEntry(entry),
    });
  };

  const openDeleteWorktreeProjectConfirm = (entry: WorkspaceEntry): void => {
    modals.openConfirmModal({
      title: t("deleteWorktreeConfirmTitle"),
      children: (
        <Text size="sm">
          {t("deleteWorktreeConfirmDescription", { path: entry.path })}
        </Text>
      ),
      labels: { confirm: t("deleteWorktree"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () => onDeleteWorktreeProjectEntry(entry),
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

  const renderCapabilityView = (
    capabilityState: Extract<
      WorkspacePanelState,
      { type: "RUNTIME_FREE" } | { type: "REMOVING" }
    >,
  ): React.ReactElement => (
    <Center h="100%" p="lg">
      <Stack align="center" gap="md" maw={rem(440)} ta="center">
        <ThemeIcon
          color={capabilityState.type === "REMOVING" ? "yellow" : "blue"}
          radius="xl"
          size="xl"
          variant="light"
        >
          <IconTerminal2 size={rem(22)} />
        </ThemeIcon>
        <Stack gap="xs">
          <Text fw={700}>
            {capabilityState.type === "REMOVING"
              ? t("removingTitle")
              : t("runtimeFreeTitle")}
          </Text>
          <Text c="dimmed" size="sm">
            {capabilityState.type === "REMOVING"
              ? t("removingDescription")
              : t("runtimeFreeDescription")}
          </Text>
          {capabilityState.type === "REMOVING" &&
          capabilityState.runtime.removal ? (
            <Text c="dimmed" size="xs">
              {t(`removalStages.${capabilityState.runtime.removal.stage}`)}
            </Text>
          ) : null}
        </Stack>
        {capabilityState.type === "RUNTIME_FREE" &&
        capabilityState.runtime.actions.add ? (
          <Button component={Link} href={runtimeSettingsHref}>
            {t("addRuntime")}
          </Button>
        ) : null}
      </Stack>
    </Center>
  );

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
    if (state.type === "RUNTIME_FREE" || state.type === "REMOVING") {
      return renderCapabilityView(state);
    }

    const { actions, lifecycle, runtime } = state.server;
    const canStartRuntime = actions.start !== null;
    const canStopRuntime = actions.stop !== null;
    const canRestartRuntime = actions.restart !== null;
    const canResetRuntime = actions.reset !== null;
    const lifecycleControl = canStopRuntime
      ? "stop"
      : canStartRuntime
        ? "start"
        : null;
    const starting = lifecycleControl === "start";

    return (
      <Stack gap="md">
        <Box>
          <Text size="lg" fw={700}>
            {t("settingsTitle")}
          </Text>
          <Text size="sm" c="dimmed">
            {t("settingsSubtitle")}
          </Text>
        </Box>

        {lifecycle ? (
          <RuntimeLifecycleStatus lifecycle={lifecycle} compact />
        ) : null}
        <RuntimeConfigurationStatus state={state.runtimeConfiguration} />

        <Paper withBorder p={{ base: "sm", sm: "md" }} radius="lg">
          <Stack gap="md">
            <Stack gap={2}>
              <Text size="sm" fw={700}>
                {t("hostControlsTitle")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("hostControlsDescription")}
              </Text>
            </Stack>

            {lifecycleControl ? (
              <Group justify="space-between" align="flex-start" gap="md">
                <Group
                  gap="sm"
                  miw={rem(200)}
                  style={{ flex: 1 }}
                  wrap="nowrap"
                >
                  <Box
                    c={starting ? "blue" : "red"}
                    style={{ display: "inline-flex" }}
                  >
                    {starting ? (
                      <IconPlayerPlay size="1rem" />
                    ) : (
                      <IconPower size="1rem" />
                    )}
                  </Box>
                  <Box miw={0}>
                    <Text size="sm" fw={600}>
                      {t(starting ? "startRuntime" : "stopRuntime")}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {t(
                        starting
                          ? "inactiveDescription"
                          : "stopRuntimeDescription",
                      )}
                    </Text>
                  </Box>
                </Group>
                <SimpleGrid
                  cols={{ base: 1, xs: canRestartRuntime ? 2 : 1 }}
                  spacing="xs"
                  w={{ base: "100%", xs: "auto" }}
                >
                  {canRestartRuntime ? (
                    <Button
                      leftSection={<IconRefresh size="1rem" />}
                      variant="default"
                      disabled={
                        state.isStarting ||
                        state.isStopping ||
                        state.isResetting
                      }
                      onClick={onOpenRestartConfirm}
                    >
                      {t("restartRuntime")}
                    </Button>
                  ) : null}
                  <Button
                    color={starting ? "blue" : "red"}
                    variant="light"
                    loading={starting ? state.isStarting : state.isStopping}
                    disabled={
                      state.isStarting || state.isStopping || state.isResetting
                    }
                    onClick={starting ? onStartRuntime : onStopRuntime}
                  >
                    {starting
                      ? state.isStarting
                        ? t("startingRuntime")
                        : t("startRuntime")
                      : state.isStopping
                        ? t("stoppingRuntime")
                        : t("stopRuntime")}
                  </Button>
                </SimpleGrid>
              </Group>
            ) : (
              <Text size="sm" c="dimmed">
                {runtime.type === "NOT_STARTED" || runtime.type === "HIBERNATED"
                  ? t("runtimeNotRunningHint")
                  : t("runtimeControlUnavailableHint")}
              </Text>
            )}

            {canResetRuntime ? (
              <Box>
                <Button
                  color="red"
                  size="xs"
                  variant="subtle"
                  loading={state.isResetting}
                  disabled={state.isStarting || state.isStopping}
                  onClick={onOpenResetConfirm}
                >
                  {t("resetRuntime")}
                </Button>
              </Box>
            ) : null}
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
    if (state.type === "RUNTIME_FREE" || state.type === "REMOVING") {
      return (
        <Box flex={1} mih={0} w="100%" style={{ overflow: "hidden" }}>
          {renderCapabilityView(state)}
        </Box>
      );
    }

    const { runtime, workspace, actions, lifecycle } = state.server;
    const isTransitioning =
      lifecycle?.availability === "transitioning" ||
      (lifecycle === null && workspace.type === "CONNECTING");
    const isInactive =
      runtime.type === "NOT_STARTED" || runtime.type === "HIBERNATED";
    const isRestoreFailed = runtime.type === "RESTORE_FAILED";
    const isRuntimeFailed = runtime.type === "LOST";
    const isControlUnavailable =
      workspace.type === "CONTROL_UNAVAILABLE" ||
      workspace.type === "READ_FAILED";
    const transitionMessage =
      lifecycle?.convergence === "stopping"
        ? "stoppingRuntime"
        : lifecycle?.convergence === "resetting"
          ? "resettingRuntime"
          : lifecycle?.convergence === "recovering"
            ? "recoveringRuntime"
            : "startingRuntime";

    return (
      <Box flex={1} mih={0} w="100%" style={{ overflow: "hidden" }}>
        {isTransitioning && (
          <Center h="100%" p="lg">
            <Stack align="center" gap="sm" maw={rem(520)} w="100%">
              {lifecycle ? (
                <RuntimeLifecycleStatus lifecycle={lifecycle} compact />
              ) : null}
              <Loader size="sm" />
              <Text size="sm" c="dimmed" ta="center">
                {t(transitionMessage)}
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
            <Stack align="center" gap="md" maw={rem(520)} w="100%">
              {lifecycle ? (
                <RuntimeLifecycleStatus lifecycle={lifecycle} compact />
              ) : null}
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
                      onClick={onOpenRestartConfirm}
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
                {actions.reset ? (
                  <Button
                    c="dimmed"
                    size="xs"
                    variant="transparent"
                    onClick={onOpenResetConfirm}
                    loading={state.isResetting}
                    disabled={state.isRefreshing || state.isStopping}
                  >
                    {t("resetRuntime")}
                  </Button>
                ) : null}
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
              {(actions.restart || actions.start || actions.reset) && (
                <Stack align="center" gap="xs">
                  {actions.restart || actions.start ? (
                    <Button
                      onClick={
                        actions.restart ? onOpenRestartConfirm : onStartRuntime
                      }
                      loading={state.isStarting}
                      disabled={state.isStarting || state.isResetting}
                    >
                      {actions.restart
                        ? t("restartRuntime")
                        : t("retryRestore")}
                    </Button>
                  ) : null}
                  {actions.reset ? (
                    <Button
                      c="dimmed"
                      size="xs"
                      variant="transparent"
                      onClick={onOpenResetConfirm}
                      loading={state.isResetting}
                      disabled={state.isStarting || state.isResetting}
                    >
                      {t("resetRuntime")}
                    </Button>
                  ) : null}
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
                  onClick={
                    actions.restart ? onOpenRestartConfirm : onStartRuntime
                  }
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
                    directoryEntriesByPath={state.directoryEntriesByPath}
                    directoryLoadStatesByPath={state.directoryLoadStatesByPath}
                    selectedFilePath={state.selectedFilePath}
                    selectedPaths={state.selectedPaths}
                    isRefreshing={state.isRefreshing}
                    browserMode={state.browserMode ?? "projects"}
                    modes={
                      state.projectBrowserManifest?.modes ?? [
                        { id: "projects", label: t("projectsMode") },
                        { id: "all_files", label: t("allFilesMode") },
                      ]
                    }
                    projectEmptyState={state.projectEmptyState ?? null}
                    query={fileBrowserQuery}
                    expanded={expandedFileNodeIds}
                    onQueryChange={onSetFileBrowserQuery}
                    onExpandedChange={onSetExpandedFileNodeIds}
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
                    onRemoveProject={openRemoveProjectConfirm}
                    onDeleteWorktreeProject={openDeleteWorktreeProjectConfirm}
                    onRefresh={onRefresh}
                    onSetBrowserMode={onSetBrowserMode}
                    onAddProject={onOpenProjectPicker}
                  />
                )}
              </Box>
            </Stack>
          )}
      </Box>
    );
  };

  return (
    <>
      <Tabs
        value={resolvedActiveTab}
        keepMounted={false}
        h="100%"
        style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}
        onChange={(value) => {
          if (
            value === "workspace" ||
            value === "metrics" ||
            value === "settings"
          ) {
            onSetActiveTab(value);
          }
        }}
      >
        <Tabs.List grow style={{ flexShrink: 0 }}>
          <Tabs.Tab
            aria-label={t("workspaceTab")}
            value="workspace"
            leftSection={<IconFolderOpen size="1rem" />}
          >
            <Text component="span" inherit visibleFrom="xs">
              {t("workspaceTab")}
            </Text>
          </Tabs.Tab>
          {metricsTabAvailable ? (
            <Tabs.Tab
              aria-label={t("metricsTab")}
              value="metrics"
              leftSection={<IconChartHistogram size="1rem" />}
            >
              <Text component="span" inherit visibleFrom="xs">
                {t("metricsTab")}
              </Text>
            </Tabs.Tab>
          ) : null}
          <Tabs.Tab
            aria-label={t("settingsTab")}
            value="settings"
            leftSection={<IconSettings size="1rem" />}
          >
            <Text component="span" inherit visibleFrom="xs">
              {t("settingsTab")}
            </Text>
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
        {metricsTabAvailable ? (
          <Tabs.Panel
            value="metrics"
            p="md"
            style={{ flex: 1, minHeight: 0, overflow: "auto" }}
          >
            <RuntimeSystemMetricsOverview state={metricsState} />
          </Tabs.Panel>
        ) : null}
        <Tabs.Panel
          value="settings"
          p="md"
          style={{ flex: 1, minHeight: 0, overflow: "auto" }}
        >
          {renderSettingsPanel()}
        </Tabs.Panel>
      </Tabs>
      <WorkspaceDirectoryPickerModal
        opened={isProjectPickerOpen}
        state={projectPickerState}
        onClose={onCloseProjectPicker}
        onOpenDirectory={onOpenProjectPickerDirectory}
        onSelectDirectory={onSelectProjectPickerDirectory}
        onRefresh={onRefreshProjectPicker}
        onStartRuntime={onStartRuntimeForProjectPicker}
        onRestartRuntime={onRestartRuntimeForProjectPicker}
        runtimeSettingsHref={runtimeSettingsHref}
      />
      <Modal
        centered
        opened={restartConfirmOpen}
        title={t("restartConfirmTitle")}
        onClose={() => onCloseRestartConfirm()}
      >
        <Stack gap="md">
          <Text size="sm">{t("restartConfirmDescription")}</Text>
          <Alert color="blue">{t("restartPreservationNotice")}</Alert>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => onCloseRestartConfirm()}>
              {t("cancel")}
            </Button>
            <Button onClick={onConfirmRestart}>{t("confirmRestart")}</Button>
          </Group>
        </Stack>
      </Modal>
      <Modal
        centered
        opened={resetConfirmOpen}
        title={t("resetRuntime")}
        onClose={() => onCloseResetConfirm()}
      >
        <Stack gap="md">
          <Text size="sm">{t("resetRuntimeConfirm")}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => onCloseResetConfirm()}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              onClick={onConfirmReset}
              loading={state.type === "SERVER" && state.isResetting}
            >
              {t("resetRuntime")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal
        centered
        opened={registrationDialog.type === "OPEN"}
        title={t("registrationModalTitle")}
        onClose={onCloseProjectRegistration}
      >
        {registrationDialog.type === "OPEN" ? (
          <Stack gap="md">
            <Box>
              <Text fw={600} size="sm">
                {basename(registrationDialog.path)}
              </Text>
              <Text c="dimmed" size="xs" style={{ overflowWrap: "anywhere" }}>
                {registrationDialog.path}
              </Text>
            </Box>
            <Select
              allowDeselect={false}
              data={[
                {
                  value: "existing_project",
                  label: t("registrationModeExistingProject"),
                },
                {
                  value: "git_worktree",
                  label: t("registrationModeGitWorktree"),
                },
              ]}
              label={t("registrationModeLabel")}
              value={registrationDialog.mode}
              onChange={(value) => {
                if (value === "existing_project" || value === "git_worktree") {
                  onSetProjectRegistrationMode(value);
                }
              }}
            />
            {registrationDialog.mode === "existing_project" ? (
              <Text c="dimmed" size="sm">
                {t("registrationExistingProjectDescription")}
              </Text>
            ) : (
              <Stack gap="xs">
                <Text c="dimmed" size="sm">
                  {t("registrationGitWorktreeDescription")}
                </Text>
                <Select
                  data={gitRefOptions}
                  disabled={
                    registrationDialog.gitRefPreview.type === "LOADING" ||
                    registrationDialog.gitRefPreview.type === "ERROR" ||
                    gitRefOptions.length === 0
                  }
                  label={t("startingRef")}
                  leftSection={
                    registrationDialog.gitRefPreview.type === "LOADING" ? (
                      <Loader size="xs" />
                    ) : (
                      <IconBrandGit size={16} />
                    )
                  }
                  placeholder={t("startingRefPlaceholder")}
                  value={registrationDialog.startingRef}
                  onChange={onSetProjectRegistrationStartingRef}
                />
                {registrationDialog.gitRefPreview.type === "ERROR" ? (
                  <Alert color="red">
                    {registrationDialog.gitRefPreview.message}
                  </Alert>
                ) : null}
                {registrationDialog.gitRefPreview.type === "READY" &&
                gitRefOptions.length === 0 ? (
                  <Text c="red" size="xs">
                    {t("noLocalBranches")}
                  </Text>
                ) : null}
              </Stack>
            )}
            {registrationDialog.submitError ? (
              <Text c="red" size="xs">
                {registrationDialog.submitError}
              </Text>
            ) : null}
            <Group justify="flex-end">
              <Button variant="default" onClick={onCloseProjectRegistration}>
                {t("cancel")}
              </Button>
              <Button
                disabled={worktreeSubmitDisabled}
                loading={registrationDialog.isSubmitting}
                onClick={onSubmitProjectRegistration}
              >
                {registrationDialog.mode === "git_worktree"
                  ? t("createWorktree")
                  : t("registerProjectSubmit")}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>
    </>
  );
}
