"use client";

/** Workspace selector for draft AgentSession creation. */

import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Loader,
  Menu,
  Paper,
  Popover,
  rem,
  ScrollArea,
  Select,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import {
  IconCheck,
  IconFolder,
  IconFolderPlus,
  IconGitBranch,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type {
  GitRefPreviewState,
  NewSessionWorkspaceItemKind,
  NewSessionWorkspaceItemState,
  ProjectPickerPurpose,
  ProjectPresetState,
} from "../containers/useAgentDraftChatContainer";

function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1) || trimmed;
}

function iconSize(): string {
  return rem(16);
}

function isWorkspaceItemKind(
  value: string | null,
): value is NewSessionWorkspaceItemKind {
  return value === "existing_project" || value === "git_worktree";
}

export interface NewSessionProjectSelectorProps {
  workspaceItems: NewSessionWorkspaceItemState[];
  activeWorktreeItemId: string | null;
  gitRefPreviewState: GitRefPreviewState;
  projectPresetState: ProjectPresetState;
  onAddPresetProject: (path: string) => void;
  onSetWorkspaceItemKind: (
    itemId: string,
    kind: NewSessionWorkspaceItemKind,
  ) => void;
  onActivateWorktreeItem: (itemId: string) => void;
  onSetWorktreeStartingRef: (itemId: string, ref: string | null) => void;
  onRemoveWorkspaceItem: (itemId: string) => void;
  onOpenProjectPicker: (purpose: ProjectPickerPurpose) => void;
}

export function NewSessionProjectSelector({
  workspaceItems,
  activeWorktreeItemId,
  gitRefPreviewState,
  projectPresetState,
  onAddPresetProject,
  onSetWorkspaceItemKind,
  onActivateWorktreeItem,
  onSetWorktreeStartingRef,
  onRemoveWorkspaceItem,
  onOpenProjectPicker,
}: NewSessionProjectSelectorProps): React.ReactElement {
  const t = useTranslations("chat");
  const presetPaths =
    projectPresetState.type === "READY"
      ? projectPresetState.presets.map((preset) => preset.path)
      : [];

  return (
    <Paper mb="sm" p="sm" radius="md" withBorder>
      <Stack gap="sm">
        <Group justify="space-between" gap="sm" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text fw={600} size="sm">
                {t("projectSelectionTitle")}
              </Text>
              <Badge size="sm" variant="light">
                {t("selectedWorkspacesCount", {
                  count: workspaceItems.length,
                })}
              </Badge>
            </Group>
            <Text c="dimmed" size="xs">
              {t("projectSelectionDescription")}
            </Text>
          </Stack>
          <AddWorkspaceMenu
            presetPaths={presetPaths}
            projectPresetState={projectPresetState}
            workspaceItems={workspaceItems}
            onAddPresetProject={onAddPresetProject}
            onOpenProjectPicker={onOpenProjectPicker}
          />
        </Group>

        {workspaceItems.length > 0 ? (
          <Stack gap="xs">
            {workspaceItems.map((item) => (
              <WorkspaceItemRow
                key={item.id}
                activeWorktreeItemId={activeWorktreeItemId}
                gitRefPreviewState={gitRefPreviewState}
                item={item}
                onActivateWorktreeItem={onActivateWorktreeItem}
                onRemoveWorkspaceItem={onRemoveWorkspaceItem}
                onSetWorkspaceItemKind={onSetWorkspaceItemKind}
                onSetWorktreeStartingRef={onSetWorktreeStartingRef}
              />
            ))}
          </Stack>
        ) : (
          <Text c="dimmed" size="xs">
            {t("projectSelectionEmpty")}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

interface AddWorkspaceMenuProps {
  presetPaths: string[];
  workspaceItems: NewSessionWorkspaceItemState[];
  projectPresetState: ProjectPresetState;
  onAddPresetProject: (path: string) => void;
  onOpenProjectPicker: (purpose: ProjectPickerPurpose) => void;
}

function AddWorkspaceMenu({
  presetPaths,
  workspaceItems,
  projectPresetState,
  onAddPresetProject,
  onOpenProjectPicker,
}: AddWorkspaceMenuProps): React.ReactElement {
  const t = useTranslations("chat");
  const selectedWorkspacePaths = workspaceItems.map((item) =>
    item.type === "existing_project" ? item.path : item.sourceProjectPath,
  );

  return (
    <Menu position="top-end" shadow="md" width={rem(380)} withinPortal>
      <Menu.Target>
        <Button leftSection={<IconPlus size={iconSize()} />} size="xs">
          {t("addWorkspace")}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{t("addRepositoryWorkspace")}</Menu.Label>
        <ScrollArea.Autosize mah={rem(220)} type="auto" offsetScrollbars>
          <ProjectPresetMenuItems
            presetPaths={presetPaths}
            projectPresetState={projectPresetState}
            selectedPaths={selectedWorkspacePaths}
            onSelect={onAddPresetProject}
          />
        </ScrollArea.Autosize>
        <Menu.Item
          leftSection={<IconFolderPlus size={iconSize()} />}
          onClick={() => onOpenProjectPicker("existing_project")}
        >
          {t("chooseFolder")}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

interface WorkspaceItemRowProps {
  item: NewSessionWorkspaceItemState;
  activeWorktreeItemId: string | null;
  gitRefPreviewState: GitRefPreviewState;
  onSetWorkspaceItemKind: (
    itemId: string,
    kind: NewSessionWorkspaceItemKind,
  ) => void;
  onActivateWorktreeItem: (itemId: string) => void;
  onSetWorktreeStartingRef: (itemId: string, ref: string | null) => void;
  onRemoveWorkspaceItem: (itemId: string) => void;
}

function WorkspaceItemRow({
  item,
  activeWorktreeItemId,
  gitRefPreviewState,
  onSetWorkspaceItemKind,
  onActivateWorktreeItem,
  onSetWorktreeStartingRef,
  onRemoveWorkspaceItem,
}: WorkspaceItemRowProps): React.ReactElement {
  switch (item.type) {
    case "existing_project":
      return (
        <ExistingProjectRow
          item={item}
          onRemoveWorkspaceItem={onRemoveWorkspaceItem}
          onSetWorkspaceItemKind={onSetWorkspaceItemKind}
        />
      );
    case "git_worktree":
      return (
        <GitWorktreeRow
          active={item.id === activeWorktreeItemId}
          gitRefPreviewState={gitRefPreviewState}
          item={item}
          onActivateWorktreeItem={onActivateWorktreeItem}
          onRemoveWorkspaceItem={onRemoveWorkspaceItem}
          onSetWorkspaceItemKind={onSetWorkspaceItemKind}
          onSetWorktreeStartingRef={onSetWorktreeStartingRef}
        />
      );
  }
}

interface WorkspaceKindSelectProps {
  value: NewSessionWorkspaceItemKind;
  itemId: string;
  onSetWorkspaceItemKind: (
    itemId: string,
    kind: NewSessionWorkspaceItemKind,
  ) => void;
}

function WorkspaceKindSelect({
  value,
  itemId,
  onSetWorkspaceItemKind,
}: WorkspaceKindSelectProps): React.ReactElement {
  const t = useTranslations("chat");
  return (
    <Select
      allowDeselect={false}
      aria-label={t("workspaceItemKindLabel")}
      data={[
        { value: "existing_project", label: t("workspaceKindRepository") },
        { value: "git_worktree", label: t("workspaceKindNewWorktree") },
      ]}
      size="xs"
      value={value}
      w={{ base: rem(132), sm: rem(168) }}
      onChange={(nextValue) => {
        if (isWorkspaceItemKind(nextValue)) {
          onSetWorkspaceItemKind(itemId, nextValue);
        }
      }}
    />
  );
}

interface ExistingProjectRowProps {
  item: Extract<NewSessionWorkspaceItemState, { type: "existing_project" }>;
  onSetWorkspaceItemKind: (
    itemId: string,
    kind: NewSessionWorkspaceItemKind,
  ) => void;
  onRemoveWorkspaceItem: (itemId: string) => void;
}

function ExistingProjectRow({
  item,
  onSetWorkspaceItemKind,
  onRemoveWorkspaceItem,
}: ExistingProjectRowProps): React.ReactElement {
  const t = useTranslations("chat");
  return (
    <Paper p="xs" radius="md" withBorder>
      <Group gap="sm" wrap="nowrap" align="center">
        <ThemeIcon variant="light" color="blue" size="sm">
          <IconFolder size={iconSize()} />
        </ThemeIcon>
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <Text fw={600} size="sm" truncate>
            {basename(item.path)}
          </Text>
          <PathPopover path={item.path} />
        </Stack>
        <WorkspaceKindSelect
          itemId={item.id}
          value={item.type}
          onSetWorkspaceItemKind={onSetWorkspaceItemKind}
        />
        <ActionIcon
          aria-label={t("removeWorkspaceItem")}
          color="red"
          size="sm"
          variant="subtle"
          onClick={() => onRemoveWorkspaceItem(item.id)}
        >
          <IconTrash size={iconSize()} />
        </ActionIcon>
      </Group>
    </Paper>
  );
}

interface GitWorktreeRowProps {
  item: Extract<NewSessionWorkspaceItemState, { type: "git_worktree" }>;
  active: boolean;
  gitRefPreviewState: GitRefPreviewState;
  onSetWorkspaceItemKind: (
    itemId: string,
    kind: NewSessionWorkspaceItemKind,
  ) => void;
  onActivateWorktreeItem: (itemId: string) => void;
  onSetWorktreeStartingRef: (itemId: string, ref: string | null) => void;
  onRemoveWorkspaceItem: (itemId: string) => void;
}

function GitWorktreeRow({
  item,
  active,
  gitRefPreviewState,
  onSetWorkspaceItemKind,
  onActivateWorktreeItem,
  onSetWorktreeStartingRef,
  onRemoveWorkspaceItem,
}: GitWorktreeRowProps): React.ReactElement {
  const t = useTranslations("chat");
  const gitRefOptions =
    active && gitRefPreviewState.type === "READY"
      ? gitRefPreviewState.refs.map((ref) => ({
          value: ref.ref,
          label: ref.default ? `${ref.name} (${t("defaultRef")})` : ref.name,
        }))
      : [];
  const loading = active && gitRefPreviewState.type === "LOADING";
  const error = active && gitRefPreviewState.type === "ERROR";
  const noLocalBranches =
    active && gitRefPreviewState.type === "READY" && gitRefOptions.length === 0;

  return (
    <Paper
      p="xs"
      radius="md"
      withBorder
      onClick={() => onActivateWorktreeItem(item.id)}
    >
      <Stack gap="xs">
        <Group gap="sm" wrap="nowrap" align="center">
          <ThemeIcon variant="light" color="grape" size="sm">
            <IconGitBranch size={iconSize()} />
          </ThemeIcon>
          <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
            <Text fw={600} size="sm" truncate>
              {basename(item.sourceProjectPath)}
            </Text>
            <PathPopover path={item.sourceProjectPath} />
          </Stack>
          <WorkspaceKindSelect
            itemId={item.id}
            value={item.type}
            onSetWorkspaceItemKind={onSetWorkspaceItemKind}
          />
          <ActionIcon
            aria-label={t("removeWorkspaceItem")}
            color="red"
            size="sm"
            variant="subtle"
            onClick={() => onRemoveWorkspaceItem(item.id)}
          >
            <IconTrash size={iconSize()} />
          </ActionIcon>
        </Group>
        <Group gap="xs" wrap="nowrap" align="flex-end">
          <Select
            data={gitRefOptions}
            disabled={loading || error || noLocalBranches}
            label={t("localBranch")}
            leftSection={loading ? <Loader size="xs" /> : null}
            placeholder={t("localBranchPlaceholder")}
            size="xs"
            value={item.startingRef}
            style={{ flex: 1 }}
            onChange={(ref) => onSetWorktreeStartingRef(item.id, ref)}
            onFocus={() => onActivateWorktreeItem(item.id)}
          />
        </Group>
        {loading ? (
          <Text c="dimmed" size="xs">
            {t("loadingLocalBranches")}
          </Text>
        ) : null}
        {error ? (
          <Text c="red" size="xs">
            {t("gitRefsErrorDescription")}
          </Text>
        ) : null}
        {noLocalBranches ? (
          <Text c="red" size="xs">
            {t("noLocalBranches")}
          </Text>
        ) : (
          <Text c="dimmed" size="xs">
            {t("localBranchesOnly")}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

interface PathPopoverProps {
  path: string;
}

function PathPopover({ path }: PathPopoverProps): React.ReactElement {
  const t = useTranslations("chat");
  return (
    <Popover position="top" shadow="md" width={rem(360)} withArrow>
      <Popover.Target>
        <Text c="dimmed" size="xs" truncate>
          {path}
        </Text>
      </Popover.Target>
      <Popover.Dropdown>
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
      </Popover.Dropdown>
    </Popover>
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
            leftSection={selected ? <IconCheck size={iconSize()} /> : null}
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
