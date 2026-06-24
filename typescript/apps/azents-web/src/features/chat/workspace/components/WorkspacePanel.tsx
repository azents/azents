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
  TextInput,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconFolderOpen,
  IconPackages,
  IconPower,
  IconSettings,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { FileBrowser } from "./FileBrowser";
import { FileViewer } from "./FileViewer";
import { RuntimeActivationView } from "./RuntimeActivationView";
import type { WorkspacePanelState, WorkspaceProjectPanelState } from "../types";

type WorkspacePanelTab = "workspace" | "projects" | "settings";

interface WorkspacePanelProps {
  state: WorkspacePanelState;
  projectState: WorkspaceProjectPanelState;
  defaultTab?: WorkspacePanelTab;
  onStartRuntime: () => void;
  onStopRuntime: () => void;
  onRestartRuntime: () => void;
  onResetRuntime: () => void;
  onOpenDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onRefresh: () => void;
  getDownloadHref: (path: string) => string;
  onRegisterProjectPathChange: (path: string) => void;
  onRegisterProject: () => void;
  onApproveRegistrationRequest: (requestId: string) => void;
  onRejectRegistrationRequest: (requestId: string) => void;
  onDeleteProject: (projectId: string) => void;
}

export function WorkspacePanel({
  state,
  projectState,
  defaultTab = "workspace",
  onStartRuntime,
  onStopRuntime,
  onRestartRuntime,
  onResetRuntime,
  onOpenDirectory,
  onOpenFile,
  onRefresh,
  getDownloadHref,
  onRegisterProjectPathChange,
  onRegisterProject,
  onApproveRegistrationRequest,
  onRejectRegistrationRequest,
  onDeleteProject,
}: WorkspacePanelProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [deleteProjectId, setDeleteProjectId] = useState<string | null>(null);

  const handleConfirmReset = (): void => {
    setResetConfirmOpen(false);
    onResetRuntime();
  };

  const handleConfirmDeleteProject = (): void => {
    if (!deleteProjectId) {
      return;
    }
    onDeleteProject(deleteProjectId);
    setDeleteProjectId(null);
  };

  const renderProjectPanel = (): React.ReactElement => {
    if (projectState.type === "LOADING") {
      return (
        <Paper withBorder p="sm" radius="md">
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm">{t("projectsLoading")}</Text>
          </Group>
        </Paper>
      );
    }

    if (projectState.type === "ERROR") {
      return (
        <Alert color="red" icon={<IconAlertCircle size="1rem" />}>
          {projectState.message}
        </Alert>
      );
    }

    const deleteProject =
      projectState.projects.find((project) => project.id === deleteProjectId) ??
      null;

    return (
      <>
        <Stack gap="md">
          <Paper withBorder p="md" radius="lg">
            <Stack gap="md">
              <Box>
                <Text size="lg" fw={700}>
                  {t("projectsTitle")}
                </Text>
                <Text size="sm" c="dimmed">
                  {t("projectsSubtitle")}
                </Text>
              </Box>

              <Stack gap="xs">
                {projectState.projects.length === 0 ? (
                  <Paper p="md" radius="md" bg="var(--mantine-color-default)">
                    <Text size="sm" c="dimmed" ta="center">
                      {t("projectsEmpty")}
                    </Text>
                  </Paper>
                ) : (
                  projectState.projects.map((project) => (
                    <Paper key={project.id} withBorder p="sm" radius="md">
                      <Group justify="space-between" align="center" gap="sm">
                        <Group gap="xs" miw={0} wrap="nowrap">
                          <Box c="blue" style={{ display: "inline-flex" }}>
                            <IconFolderOpen size="1rem" />
                          </Box>
                          <Text size="sm" fw={600} truncate>
                            {project.path}
                          </Text>
                        </Group>
                        <Button
                          size="xs"
                          variant="light"
                          color="red"
                          loading={
                            projectState.pendingDeleteProjectId === project.id
                          }
                          onClick={() => setDeleteProjectId(project.id)}
                        >
                          {t("deleteProject")}
                        </Button>
                      </Group>
                    </Paper>
                  ))
                )}
              </Stack>
            </Stack>
          </Paper>

          <Paper withBorder p="md" radius="lg">
            <Stack gap="sm">
              <Box>
                <Text size="lg" fw={700}>
                  {t("registerProjectTitle")}
                </Text>
                <Text size="sm" c="dimmed">
                  {t("registerProjectSubtitle")}
                </Text>
              </Box>
              <TextInput
                label={t("registerProjectPath")}
                value={projectState.registerProjectPath}
                onChange={(event) =>
                  onRegisterProjectPathChange(event.currentTarget.value)
                }
              />
              {projectState.registerProjectError && (
                <Text size="xs" c="red">
                  {projectState.registerProjectError}
                </Text>
              )}
              <Button
                loading={projectState.isRegisteringProject}
                onClick={onRegisterProject}
                fullWidth
              >
                {t("registerProjectSubmit")}
              </Button>
            </Stack>
          </Paper>

          <Paper withBorder p="md" radius="lg">
            <Stack gap="sm">
              <Text size="lg" fw={700}>
                {t("requestsTitle")}
              </Text>
              {projectState.registrationRequests.length === 0 ? (
                <Text size="sm" c="dimmed">
                  {t("requestsEmpty")}
                </Text>
              ) : (
                projectState.registrationRequests.map((request) => (
                  <Paper key={request.id} withBorder p="sm" radius="md">
                    <Stack gap="sm">
                      <Box>
                        <Text size="sm" fw={600} truncate>
                          {request.path}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {request.reason}
                        </Text>
                      </Box>
                      <Group gap="xs">
                        <Button
                          size="xs"
                          onClick={() =>
                            onApproveRegistrationRequest(request.id)
                          }
                          loading={
                            projectState.pendingApproveRequestId === request.id
                          }
                        >
                          {t("approveRequest")}
                        </Button>
                        <Button
                          size="xs"
                          variant="light"
                          color="gray"
                          onClick={() =>
                            onRejectRegistrationRequest(request.id)
                          }
                          loading={
                            projectState.pendingRejectRequestId === request.id
                          }
                        >
                          {t("rejectRequest")}
                        </Button>
                      </Group>
                    </Stack>
                  </Paper>
                ))
              )}
            </Stack>
          </Paper>
        </Stack>

        <Modal
          opened={deleteProject !== null}
          onClose={() => setDeleteProjectId(null)}
          title={t("deleteProjectConfirmTitle")}
          centered
        >
          <Stack gap="md">
            <Text size="sm">
              {t("deleteProjectConfirmDescription", {
                path: deleteProject?.path ?? "",
              })}
            </Text>
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setDeleteProjectId(null)}
              >
                {t("cancel")}
              </Button>
              <Button
                color="red"
                onClick={handleConfirmDeleteProject}
                loading={
                  deleteProject !== null &&
                  projectState.pendingDeleteProjectId === deleteProject.id
                }
              >
                {t("deleteProject")}
              </Button>
            </Group>
          </Stack>
        </Modal>
      </>
    );
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
          state.manifest &&
          (state.fileState.type === "IDLE" ? (
            <FileBrowser
              root={state.manifest.root}
              cwd={state.manifest.cwd}
              path={state.directory.path}
              manifestEntries={state.manifest.entries}
              entries={state.directory.entries}
              directoryEntriesByPath={state.directoryEntriesByPath}
              selectedFilePath={state.selectedFilePath}
              isRefreshing={state.isRefreshing}
              onOpenDirectory={onOpenDirectory}
              onOpenFile={onOpenFile}
              onRefresh={onRefresh}
            />
          ) : (
            <FileViewer
              state={state.fileState}
              getDownloadHref={getDownloadHref}
              onBack={() => onOpenDirectory(state.directory.path)}
            />
          ))}
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
        <Tabs.Tab value="projects" leftSection={<IconPackages size="1rem" />}>
          {t("projectsTab")}
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
        value="projects"
        p="md"
        style={{ flex: 1, minHeight: 0, overflow: "auto" }}
      >
        {renderProjectPanel()}
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
