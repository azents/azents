"use client";

/** Project selector for draft AgentSession creation. */

import {
  Button,
  Divider,
  Group,
  Loader,
  Menu,
  Paper,
  Popover,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconCheck,
  IconFolderPlus,
  IconPlus,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { ProjectPresetState } from "../containers/useAgentDraftChatContainer";

function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1) || trimmed;
}

export interface NewSessionProjectSelectorProps {
  selectedProjectPaths: string[];
  projectPresetState: ProjectPresetState;
  onAddPresetProject: (path: string) => void;
  onRemoveProject: (path: string) => void;
  onOpenProjectPicker: () => void;
}

export function NewSessionProjectSelector({
  selectedProjectPaths,
  projectPresetState,
  onAddPresetProject,
  onRemoveProject,
  onOpenProjectPicker,
}: NewSessionProjectSelectorProps): React.ReactElement {
  const t = useTranslations("chat");
  const presetPaths =
    projectPresetState.type === "READY"
      ? projectPresetState.presets.map((preset) => preset.path)
      : [];

  return (
    <Paper mb="sm" p="sm" radius="md" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" gap="sm">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={600} size="sm">
              {t("projectSelectionTitle")}
            </Text>
            <Text c="dimmed" size="xs">
              {t("projectSelectionDescription")}
            </Text>
          </Stack>
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
                {projectPresetState.type === "READY" &&
                presetPaths.length === 0 ? (
                  <Menu.Item disabled>
                    {t("projectSelectionEmptyPresets")}
                  </Menu.Item>
                ) : null}
                {presetPaths.map((path) => {
                  const selected = selectedProjectPaths.includes(path);
                  return (
                    <Menu.Item
                      key={path}
                      disabled={selected}
                      leftSection={selected ? <IconCheck size={16} /> : null}
                      onClick={() => onAddPresetProject(path)}
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
    </Paper>
  );
}
