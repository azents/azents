"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Paper,
  rem,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronUp,
  IconFolder,
  IconFolderPlus,
  IconRefresh,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { AgentWorkspaceDirectoryPickerModal } from "@/features/agent-workspace/components/AgentWorkspaceDirectoryPickerModal";
import {
  automaticProjectsEditingDisabled,
  automaticProjectsSaveEnabled,
} from "../automaticProjects";
import type {
  AutomaticProjectRow,
  AutomaticProjectsState,
} from "../automaticProjects";
import type { ProjectDirectoryPickerEntry } from "@/features/agent-workspace/types";

interface AgentAutomaticProjectsProps {
  state: AutomaticProjectsState;
  isProjectPickerOpen: boolean;
  pickerState: Parameters<
    typeof AgentWorkspaceDirectoryPickerModal
  >[0]["state"];
  onAddProject: () => void;
  onCloseProjectPicker: () => void;
  onOpenProjectPickerDirectory: (path: string) => void;
  onSelectProjectPickerDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  onRefreshProjectPicker: () => void;
  onStartRuntimeForProjectPicker: () => void;
  onRemoveProject: (path: string) => void;
  onMoveProject: (path: string, direction: "up" | "down") => void;
  onSave: () => Promise<void>;
  onRetrySave: () => Promise<void>;
  onReloadLatest: () => Promise<void>;
}

function statusColor(status: AutomaticProjectRow["status"]): string {
  switch (status) {
    case "available":
      return "green";
    case "missing":
      return "red";
    case "unavailable":
    case "error":
      return "orange";
    case "unchecked":
      return "gray";
  }
}

function statusLabel(
  t: ReturnType<typeof useTranslations>,
  status: AutomaticProjectRow["status"],
): string {
  switch (status) {
    case "available":
      return t("status.available");
    case "missing":
      return t("status.missing");
    case "unavailable":
      return t("status.unavailable");
    case "error":
      return t("status.error");
    case "unchecked":
      return t("status.unchecked");
  }
}

function rowsFromState(state: AutomaticProjectsState): AutomaticProjectRow[] {
  switch (state.type) {
    case "LOADING":
    case "ERROR":
    case "EMPTY":
      return [];
    case "CLEAN":
    case "DIRTY":
    case "SAVING":
    case "RUNTIME_UNAVAILABLE":
    case "MISSING":
    case "VALIDATION_ERROR":
    case "CONFLICT":
    case "EDITOR_ERROR":
      return state.rows;
  }
}

function stateMessage(state: AutomaticProjectsState): string | null {
  switch (state.type) {
    case "RUNTIME_UNAVAILABLE":
    case "MISSING":
    case "VALIDATION_ERROR":
    case "CONFLICT":
      return state.message;
    case "ERROR":
      return state.message;
    case "EDITOR_ERROR":
      return state.message;
    default:
      return null;
  }
}

function isReloadVisible(state: AutomaticProjectsState): boolean {
  return state.type === "CONFLICT";
}

function hasUnsavedDraft(state: AutomaticProjectsState): boolean {
  switch (state.type) {
    case "DIRTY":
    case "SAVING":
    case "RUNTIME_UNAVAILABLE":
    case "VALIDATION_ERROR":
    case "CONFLICT":
    case "EDITOR_ERROR":
      return true;
    case "MISSING":
      return state.dirty;
    default:
      return false;
  }
}

export function AgentAutomaticProjects({
  state,
  isProjectPickerOpen,
  pickerState,
  onAddProject,
  onCloseProjectPicker,
  onOpenProjectPickerDirectory,
  onSelectProjectPickerDirectory,
  onRefreshProjectPicker,
  onStartRuntimeForProjectPicker,
  onRemoveProject,
  onMoveProject,
  onSave,
  onRetrySave,
  onReloadLatest,
}: AgentAutomaticProjectsProps): React.ReactElement {
  const t = useTranslations("workspace.agents.automaticProjects");
  const rows = rowsFromState(state);
  const message =
    state.type === "MISSING" ? t("missingDescription") : stateMessage(state);
  const saveEnabled = automaticProjectsSaveEnabled(state);
  const reloadVisible = isReloadVisible(state);
  const editingDisabled = automaticProjectsEditingDisabled(state);

  if (state.type === "LOADING") {
    return (
      <Box style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
        <Stack gap="lg" p="md" maw={rem(860)} mx="auto" w="100%">
          <Skeleton height={rem(34)} width="60%" />
          <Skeleton height={rem(80)} />
          <Skeleton height={rem(80)} />
        </Stack>
      </Box>
    );
  }

  if (state.type === "ERROR") {
    return (
      <Box style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
        <Stack gap="lg" p="md" maw={rem(860)} mx="auto" w="100%">
          <Alert color="red" title={t("errorTitle")}>
            {state.message}
          </Alert>
          <Button
            leftSection={<IconRefresh size={rem(16)} />}
            onClick={() => void onReloadLatest()}
          >
            {t("reloadLatest")}
          </Button>
        </Stack>
      </Box>
    );
  }

  return (
    <Box style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
      <Stack
        data-testid="automatic-projects-page"
        gap="xl"
        p="md"
        maw={rem(860)}
        mx="auto"
        w="100%"
      >
        <Stack gap="xs" px="xs">
          <Text fw={700} size="xl">
            {t("title")}
          </Text>
          <Text size="sm" c="dimmed">
            {t("description")}
          </Text>
        </Stack>

        {message ? (
          <Alert
            color={
              state.type === "CONFLICT" || state.type === "MISSING"
                ? "orange"
                : "red"
            }
            icon={<IconAlertTriangle size={rem(18)} />}
            title={
              state.type === "CONFLICT"
                ? t("conflictTitle")
                : state.type === "RUNTIME_UNAVAILABLE"
                  ? t("runtimeUnavailableTitle")
                  : state.type === "MISSING"
                    ? t("missingTitle")
                    : state.type === "EDITOR_ERROR"
                      ? t("errorTitle")
                      : t("validationTitle")
            }
          >
            <Stack gap="xs">
              <Text size="sm">{message}</Text>
              {state.type === "RUNTIME_UNAVAILABLE" ? (
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="light"
                    onClick={onStartRuntimeForProjectPicker}
                  >
                    {t("startRuntime")}
                  </Button>
                  <Button size="xs" onClick={() => void onRetrySave()}>
                    {t("retrySave")}
                  </Button>
                </Group>
              ) : null}
              {reloadVisible ? (
                <Button
                  data-testid="automatic-projects-reload-latest"
                  size="xs"
                  variant="light"
                  onClick={() => void onReloadLatest()}
                >
                  {t("reloadLatest")}
                </Button>
              ) : null}
            </Stack>
          </Alert>
        ) : null}

        <Card withBorder radius="lg" padding="md">
          <Stack gap="md">
            <Group justify="space-between" align="flex-start" wrap="wrap">
              <Stack gap="xs">
                <Text fw={600}>{t("listTitle")}</Text>
                <Text size="sm" c="dimmed">
                  {t("listDescription")}
                </Text>
              </Stack>
              <Button
                data-testid="automatic-projects-add"
                disabled={editingDisabled}
                leftSection={<IconFolderPlus size={rem(16)} />}
                onClick={onAddProject}
              >
                {t("addProject")}
              </Button>
            </Group>

            {rows.length === 0 ? (
              <Center py="xl">
                <Stack align="center" gap="xs">
                  <ThemeIcon color="gray" radius="xl" size={rem(42)}>
                    <IconFolder size={rem(20)} />
                  </ThemeIcon>
                  <Text ta="center" size="sm" c="dimmed">
                    {t("empty")}
                  </Text>
                </Stack>
              </Center>
            ) : (
              <Stack gap="xs">
                {rows.map((row, index) => (
                  <Paper
                    key={row.path}
                    data-testid={`automatic-project-row-${row.path}`}
                    withBorder
                    p="sm"
                    radius="md"
                  >
                    <Group
                      justify="space-between"
                      align="flex-start"
                      wrap="nowrap"
                    >
                      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                        <ThemeIcon color="gray" variant="light" radius="xl">
                          <IconFolder size={rem(17)} />
                        </ThemeIcon>
                        <Stack gap="xs" style={{ minWidth: 0 }}>
                          <Group gap="xs" wrap="wrap">
                            <Text fw={600}>{row.name}</Text>
                            <Badge
                              color={statusColor(row.status)}
                              variant="light"
                            >
                              {statusLabel(t, row.status)}
                            </Badge>
                          </Group>
                          <Text
                            data-testid={`automatic-project-path-${row.path}`}
                            size="sm"
                            c="dimmed"
                            style={{ overflowWrap: "anywhere" }}
                          >
                            {row.path}
                          </Text>
                          {row.detail ? (
                            <Text size="xs" c="dimmed">
                              {row.detail}
                            </Text>
                          ) : null}
                        </Stack>
                      </Group>
                      <Group gap="xs" wrap="nowrap">
                        <Tooltip label={t("moveUp")}>
                          <ActionButton
                            dataTestId={`automatic-project-move-up-${row.path}`}
                            label={t("moveUp")}
                            disabled={editingDisabled || index === 0}
                            onClick={() => onMoveProject(row.path, "up")}
                          >
                            <IconChevronUp size={rem(16)} />
                          </ActionButton>
                        </Tooltip>
                        <Tooltip label={t("moveDown")}>
                          <ActionButton
                            dataTestId={`automatic-project-move-down-${row.path}`}
                            label={t("moveDown")}
                            disabled={
                              editingDisabled || index === rows.length - 1
                            }
                            onClick={() => onMoveProject(row.path, "down")}
                          >
                            <IconChevronDown size={rem(16)} />
                          </ActionButton>
                        </Tooltip>
                        <Tooltip label={t("removeProject")}>
                          <ActionButton
                            dataTestId={`automatic-project-remove-${row.path}`}
                            label={t("removeProject")}
                            color="red"
                            disabled={editingDisabled}
                            onClick={() => onRemoveProject(row.path)}
                          >
                            <IconTrash size={rem(16)} />
                          </ActionButton>
                        </Tooltip>
                      </Group>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            )}

            <Group justify="space-between" align="center" wrap="wrap">
              <Text size="sm" c="dimmed">
                {hasUnsavedDraft(state) ? t("unsaved") : t("saved")}
              </Text>
              <Button
                data-testid="automatic-projects-save"
                loading={state.type === "SAVING"}
                disabled={!saveEnabled}
                onClick={() => void onSave()}
              >
                {t("saveChanges")}
              </Button>
            </Group>
          </Stack>
        </Card>
      </Stack>

      <AgentWorkspaceDirectoryPickerModal
        opened={isProjectPickerOpen}
        state={pickerState}
        translationNamespace="agentWorkspacePicker"
        onClose={onCloseProjectPicker}
        onOpenDirectory={onOpenProjectPickerDirectory}
        onSelectDirectory={onSelectProjectPickerDirectory}
        onRefresh={onRefreshProjectPicker}
        onStartRuntime={onStartRuntimeForProjectPicker}
      />
    </Box>
  );
}

interface ActionButtonProps {
  label: string;
  dataTestId?: string;
  disabled?: boolean;
  color?: string;
  onClick: () => void;
  children: React.ReactNode;
}

function ActionButton({
  label,
  dataTestId,
  disabled,
  color,
  onClick,
  children,
}: ActionButtonProps): React.ReactElement {
  return (
    <Button
      aria-label={label}
      data-testid={dataTestId}
      color={color}
      disabled={disabled}
      p={rem(6)}
      size="compact-sm"
      variant="subtle"
      onClick={onClick}
    >
      {children}
    </Button>
  );
}
