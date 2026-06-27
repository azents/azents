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
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertCircle, IconFolderOpen } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type { WorkspaceProjectPanelState } from "../types";

interface ProjectPanelProps {
  projectState: WorkspaceProjectPanelState;
  onRegisterProjectPathChange: (path: string) => void;
  onRegisterProject: () => void;
  onApproveRegistrationRequest: (requestId: string) => void;
  onRejectRegistrationRequest: (requestId: string) => void;
  onDeleteProject: (projectId: string) => void;
}

export function ProjectPanel({
  projectState,
  onRegisterProjectPathChange,
  onRegisterProject,
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
