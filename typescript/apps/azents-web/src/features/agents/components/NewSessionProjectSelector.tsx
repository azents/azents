"use client";

/** Project selector for draft AgentSession creation. */

import {
  Alert,
  Button,
  Divider,
  Group,
  Loader,
  Menu,
  Paper,
  Popover,
  rem,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconCheck,
  IconFolderPlus,
  IconGitBranch,
  IconPlus,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type {
  GitRefPreviewState,
  NewSessionWorkspaceModeState,
  ProjectPresetState,
} from "../containers/useAgentDraftChatContainer";

function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1) || trimmed;
}

export interface NewSessionProjectSelectorProps {
  selectedProjectPaths: string[];
  workspaceMode: NewSessionWorkspaceModeState;
  gitRefPreviewState: GitRefPreviewState;
  projectPresetState: ProjectPresetState;
  onSelectExistingProjectsMode: () => void;
  onSelectGitWorktreeMode: () => void;
  onAddPresetProject: (path: string) => void;
  onSetWorktreeSourceProject: (path: string) => void;
  onSetWorktreeStartingRef: (ref: string | null) => void;
  onRemoveProject: (path: string) => void;
  onOpenProjectPicker: () => void;
}

export function NewSessionProjectSelector({
  selectedProjectPaths,
  workspaceMode,
  gitRefPreviewState,
  projectPresetState,
  onSelectExistingProjectsMode,
  onSelectGitWorktreeMode,
  onAddPresetProject,
  onSetWorktreeSourceProject,
  onSetWorktreeStartingRef,
  onRemoveProject,
  onOpenProjectPicker,
}: NewSessionProjectSelectorProps): React.ReactElement {
  const t = useTranslations("chat");
  const presetPaths =
    projectPresetState.type === "READY"
      ? projectPresetState.presets.map((preset) => preset.path)
      : [];
  const gitRefOptions =
    gitRefPreviewState.type === "READY"
      ? gitRefPreviewState.refs.map((ref) => ({
          value: ref.ref,
          label: ref.default ? `${ref.name} (${t("defaultRef")})` : ref.name,
        }))
      : [];
  const selectedStartingRef =
    workspaceMode.type === "git_worktree" ? workspaceMode.startingRef : null;
  const sourceProjectPath =
    workspaceMode.type === "git_worktree"
      ? workspaceMode.sourceProjectPath
      : null;

  return (
    <Paper mb="sm" p="sm" radius="md" withBorder>
      <Stack gap="sm">
        <Group justify="space-between" gap="sm" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={600} size="sm">
              {t("projectSelectionTitle")}
            </Text>
            <Text c="dimmed" size="xs">
              {t("projectSelectionDescription")}
            </Text>
          </Stack>
          <SegmentedControl
            size="xs"
            value={workspaceMode.type}
            data={[
              { value: "existing_projects", label: t("existingProjectsMode") },
              { value: "git_worktree", label: t("gitWorktreeMode") },
            ]}
            onChange={(value) => {
              if (value === "git_worktree") {
                onSelectGitWorktreeMode();
              } else {
                onSelectExistingProjectsMode();
              }
            }}
          />
        </Group>

        {workspaceMode.type === "existing_projects" ? (
          <ExistingProjectsSelector
            presetPaths={presetPaths}
            projectPresetState={projectPresetState}
            selectedProjectPaths={selectedProjectPaths}
            onAddPresetProject={onAddPresetProject}
            onOpenProjectPicker={onOpenProjectPicker}
            onRemoveProject={onRemoveProject}
          />
        ) : (
          <Stack gap="xs">
            <Group justify="space-between" gap="xs" align="flex-start">
              <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
                <Text fw={500} size="sm">
                  {t("worktreeSourceProject")}
                </Text>
                {sourceProjectPath ? (
                  <Popover position="top" shadow="md" width={360} withArrow>
                    <Popover.Target>
                      <Button
                        justify="flex-start"
                        leftSection={<IconGitBranch size={14} />}
                        size="compact-sm"
                        variant="light"
                        style={{ maxWidth: "100%" }}
                      >
                        <Text component="span" size="xs" truncate>
                          {sourceProjectPath}
                        </Text>
                      </Button>
                    </Popover.Target>
                    <Popover.Dropdown>
                      <Stack gap={2}>
                        <Text fw={600} size="sm">
                          {basename(sourceProjectPath)}
                        </Text>
                        <Text c="dimmed" size="xs">
                          {t("fullPath")}
                        </Text>
                        <Text size="xs" style={{ overflowWrap: "anywhere" }}>
                          {sourceProjectPath}
                        </Text>
                      </Stack>
                    </Popover.Dropdown>
                  </Popover>
                ) : (
                  <Text c="dimmed" size="xs">
                    {t("worktreeSourceEmpty")}
                  </Text>
                )}
              </Stack>
              <Menu position="top-end" shadow="md" width={360} withinPortal>
                <Menu.Target>
                  <Button
                    leftSection={<IconFolderPlus size={16} />}
                    size="xs"
                    variant="light"
                  >
                    {t("chooseSourceProject")}
                  </Button>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label>{t("projectSelectionPresets")}</Menu.Label>
                  <ScrollArea.Autosize
                    mah={rem(360)}
                    type="auto"
                    offsetScrollbars
                  >
                    <ProjectPresetMenuItems
                      presetPaths={presetPaths}
                      projectPresetState={projectPresetState}
                      selectedPaths={
                        sourceProjectPath ? [sourceProjectPath] : []
                      }
                      onSelect={onSetWorktreeSourceProject}
                    />
                  </ScrollArea.Autosize>
                  <Menu.Divider />
                  <Menu.Item
                    leftSection={<IconFolderPlus size={16} />}
                    onClick={onOpenProjectPicker}
                  >
                    {t("chooseFolder")}
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            </Group>
            <Select
              data={gitRefOptions}
              disabled={
                sourceProjectPath === null ||
                gitRefPreviewState.type !== "READY"
              }
              label={t("startingRef")}
              placeholder={
                sourceProjectPath === null
                  ? t("selectSourceProjectFirst")
                  : t("startingRefPlaceholder")
              }
              value={selectedStartingRef}
              onChange={onSetWorktreeStartingRef}
            />
            {sourceProjectPath === null ? (
              <Alert color="blue" py="xs">
                <Text size="xs">{t("selectSourceProjectFirst")}</Text>
              </Alert>
            ) : selectedStartingRef === null ? (
              <Alert color="blue" py="xs">
                <Text size="xs">{t("startingRefPlaceholder")}</Text>
              </Alert>
            ) : null}
            {gitRefPreviewState.type === "LOADING" ? (
              <Group gap="xs">
                <Loader size="xs" />
                <Text c="dimmed" size="xs">
                  {t("loadingGitRefs")}
                </Text>
              </Group>
            ) : null}
            {gitRefPreviewState.type === "ERROR" ? (
              <Alert color="red" py="xs" title={t("gitRefsErrorTitle")}>
                <Text size="xs">{t("gitRefsErrorDescription")}</Text>
              </Alert>
            ) : null}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

interface ExistingProjectsSelectorProps {
  presetPaths: string[];
  selectedProjectPaths: string[];
  projectPresetState: ProjectPresetState;
  onAddPresetProject: (path: string) => void;
  onRemoveProject: (path: string) => void;
  onOpenProjectPicker: () => void;
}

function ExistingProjectsSelector({
  presetPaths,
  selectedProjectPaths,
  projectPresetState,
  onAddPresetProject,
  onRemoveProject,
  onOpenProjectPicker,
}: ExistingProjectsSelectorProps): React.ReactElement {
  const t = useTranslations("chat");
  return (
    <Stack gap="xs">
      <Group justify="flex-end">
        <Menu position="top-end" shadow="md" width={360} withinPortal>
          <Menu.Target>
            <Button
              leftSection={<IconPlus size={16} />}
              size="xs"
              variant="light"
            >
              {t("addProject")}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>{t("projectSelectionPresets")}</Menu.Label>
            <ScrollArea.Autosize mah={rem(360)} type="auto" offsetScrollbars>
              <ProjectPresetMenuItems
                presetPaths={presetPaths}
                projectPresetState={projectPresetState}
                selectedPaths={selectedProjectPaths}
                onSelect={onAddPresetProject}
              />
            </ScrollArea.Autosize>
            <Menu.Divider />
            <Menu.Item
              leftSection={<IconFolderPlus size={16} />}
              onClick={onOpenProjectPicker}
            >
              {t("chooseFolder")}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>

      {selectedProjectPaths.length > 0 ? (
        <Group gap="xs">
          {selectedProjectPaths.map((path) => (
            <Popover
              key={path}
              position="top"
              shadow="md"
              width={360}
              withArrow
            >
              <Popover.Target>
                <Button size="compact-xs" variant="light">
                  {basename(path)}
                </Button>
              </Popover.Target>
              <Popover.Dropdown>
                <Stack gap="xs">
                  <Stack gap={2}>
                    <Text fw={600} size="sm">
                      {basename(path)}
                    </Text>
                    <Text c="dimmed" size="xs">
                      {t("fullPath")}
                    </Text>
                    <Text size="xs" style={{ overflowWrap: "anywhere" }}>
                      {path}
                    </Text>
                  </Stack>
                  <Divider />
                  <Group justify="flex-end">
                    <Button
                      color="red"
                      leftSection={<IconX size={14} />}
                      size="xs"
                      variant="subtle"
                      onClick={() => onRemoveProject(path)}
                    >
                      {t("removeProject")}
                    </Button>
                  </Group>
                </Stack>
              </Popover.Dropdown>
            </Popover>
          ))}
        </Group>
      ) : (
        <Text c="dimmed" size="xs">
          {t("projectSelectionEmpty")}
        </Text>
      )}
    </Stack>
  );
}

interface ProjectPresetMenuItemsProps {
  presetPaths: string[];
  selectedPaths: string[];
  projectPresetState: ProjectPresetState;
  onSelect: (path: string) => void;
}

function ProjectPresetMenuItems({
  presetPaths,
  selectedPaths,
  projectPresetState,
  onSelect,
}: ProjectPresetMenuItemsProps): React.ReactElement {
  const t = useTranslations("chat");
  return (
    <>
      {projectPresetState.type === "LOADING" ? (
        <Menu.Item disabled leftSection={<Loader size="xs" />}>
          {t("projectSelectionLoading")}
        </Menu.Item>
      ) : null}
      {projectPresetState.type === "ERROR" ? (
        <Menu.Item color="red" disabled>
          {t("projectSelectionError")}
        </Menu.Item>
      ) : null}
      {projectPresetState.type === "READY" && presetPaths.length === 0 ? (
        <Menu.Item disabled>{t("projectSelectionEmptyPresets")}</Menu.Item>
      ) : null}
      {presetPaths.map((path) => {
        const selected = selectedPaths.includes(path);
        return (
          <Menu.Item
            key={path}
            disabled={selected}
            leftSection={selected ? <IconCheck size={16} /> : null}
            onClick={() => onSelect(path)}
          >
            <Stack gap={2} miw={0}>
              <Text fw={500} size="sm" truncate>
                {basename(path)}
              </Text>
              <Text c="dimmed" size="xs" truncate>
                {path}
              </Text>
            </Stack>
          </Menu.Item>
        );
      })}
    </>
  );
}
