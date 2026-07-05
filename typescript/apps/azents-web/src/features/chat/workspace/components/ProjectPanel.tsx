"use client";

/** Session-scoped Project management panel. */
import {
  Alert,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconBrandGit,
  IconFolderOpen,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { WorkspaceDirectoryPickerModal } from "./WorkspaceDirectoryPickerModal";
import type {
  ProjectRegistrationMode,
  WorkspaceProjectPanelState,
} from "../types";
import type {
  ProjectDirectoryPickerEntry,
  ProjectDirectoryPickerState,
} from "./WorkspaceDirectoryPickerModal";

interface ProjectPanelProps {
  projectState: WorkspaceProjectPanelState;
  projectPickerState: ProjectDirectoryPickerState;
  isProjectPickerOpen: boolean;
  onOpenProjectPicker: () => void;
  onCloseProjectPicker: () => void;
  onOpenProjectPickerDirectory: (path: string) => void;
  onSelectProjectPickerDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  onRefreshProjectPicker: () => void;
  onStartRuntimeForProjectPicker: () => void;
  onCloseProjectRegistration: () => void;
  onSetProjectRegistrationMode: (mode: ProjectRegistrationMode) => void;
  onSetProjectRegistrationStartingRef: (ref: string | null) => void;
  onSubmitProjectRegistration: () => void;
  onApproveRegistrationRequest: (requestId: string) => void;
  onRejectRegistrationRequest: (requestId: string) => void;
  onDeleteProject: (projectId: string) => void;
}

export function ProjectPanel({
  projectState,
  projectPickerState,
  isProjectPickerOpen,
  onOpenProjectPicker,
  onCloseProjectPicker,
  onOpenProjectPickerDirectory,
  onSelectProjectPickerDirectory,
  onRefreshProjectPicker,
  onStartRuntimeForProjectPicker,
  onCloseProjectRegistration,
  onSetProjectRegistrationMode,
  onSetProjectRegistrationStartingRef,
  onSubmitProjectRegistration,
  onApproveRegistrationRequest,
  onRejectRegistrationRequest,
  onDeleteProject,
}: ProjectPanelProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const [deleteProjectId, setDeleteProjectId] = useState<string | null>(null);

  const handleConfirmDeleteProject = (): void => {
    if (!deleteProjectId) {
      return;
    }
    onDeleteProject(deleteProjectId);
    setDeleteProjectId(null);
  };

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
  const basename = (path: string): string => {
    const trimmed = path.replace(/\/+$/, "");
    return trimmed.slice(trimmed.lastIndexOf("/") + 1) || trimmed;
  };
  const registrationDialog = projectState.registrationDialog;
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
                        <Box miw={0}>
                          <Text size="sm" fw={600} truncate>
                            {basename(project.path)}
                          </Text>
                          <Text size="xs" c="dimmed" truncate>
                            {project.path}
                          </Text>
                        </Box>
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
            {projectState.registerProjectError && (
              <Text size="xs" c="red">
                {projectState.registerProjectError}
              </Text>
            )}
            <Button
              leftSection={<IconFolderOpen size="1rem" />}
              loading={projectState.isRegisteringProject}
              onClick={onOpenProjectPicker}
              fullWidth
            >
              {t("registerProjectBrowse")}
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
                        onClick={() => onApproveRegistrationRequest(request.id)}
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
                        onClick={() => onRejectRegistrationRequest(request.id)}
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

      <WorkspaceDirectoryPickerModal
        opened={isProjectPickerOpen}
        state={projectPickerState}
        onClose={onCloseProjectPicker}
        onOpenDirectory={onOpenProjectPickerDirectory}
        onSelectDirectory={onSelectProjectPickerDirectory}
        onRefresh={onRefreshProjectPicker}
        onStartRuntime={onStartRuntimeForProjectPicker}
      />

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
            <Button variant="default" onClick={() => setDeleteProjectId(null)}>
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
}
