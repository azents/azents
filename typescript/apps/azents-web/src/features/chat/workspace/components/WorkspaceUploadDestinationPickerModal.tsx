"use client";

import {
  ActionIcon,
  Alert,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  rem,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronRight, IconFolder, IconRefresh } from "@tabler/icons-react";
import type { WorkspacePanelTranslator } from "../containers/useWorkspacePanelTranslations";
import type { AgentWorkspaceDirectoryPickerContainerOutput } from "@/shared/agent-workspace/containers/useAgentWorkspaceDirectoryPickerContainer";
import type { ProjectDirectoryPickerEntry } from "@/shared/agent-workspace/types";

interface WorkspaceUploadDestinationPickerModalProps {
  picker: AgentWorkspaceDirectoryPickerContainerOutput;
  t: WorkspacePanelTranslator;
}

function parentPath(path: string, root: string): string | null {
  const trimmed = path.replace(/\/+$/, "");
  const index = trimmed.lastIndexOf("/");
  if (index <= 0) {
    return null;
  }
  const parent = trimmed.slice(0, index);
  return parent === root || parent.startsWith(`${root}/`) ? parent : null;
}

function currentDirectoryEntry(path: string): ProjectDirectoryPickerEntry {
  return { path, kind: "directory", repositoryType: null };
}

export function WorkspaceUploadDestinationPickerModal({
  picker,
  t,
}: WorkspaceUploadDestinationPickerModalProps): React.ReactElement {
  const renderContent = (): React.ReactElement => {
    const { state } = picker;
    if (state.type === "LOADING") {
      return (
        <Center py="xl">
          <Loader size="sm" />
        </Center>
      );
    }
    if (state.type === "ERROR") {
      return <Alert color="red">{state.message}</Alert>;
    }
    if (state.type === "RUNTIME_FREE" || state.type === "REMOVING") {
      return (
        <Alert color="blue" title={t("inactiveTitle")}>
          {t("inactiveDescription")}
        </Alert>
      );
    }
    if (state.type !== "SERVER") {
      return <Alert color="blue">{t("inactiveDescription")}</Alert>;
    }
    if (state.server.workspace.type !== "READY") {
      return (
        <Alert color="blue" title={t("inactiveTitle")}>
          {t("inactiveDescription")}
        </Alert>
      );
    }

    const root = state.server.workspace.manifest.root;
    const parent = parentPath(state.currentPath, root);
    const directories = state.entries.filter(
      (entry) => entry.kind === "directory",
    );

    return (
      <Stack gap="md">
        <Text c="dimmed" size="sm">
          {t("upload.destinationDescription")}
        </Text>
        <Group justify="space-between" wrap="nowrap">
          <Text c="dimmed" size="xs">
            {t("upload.destinationCurrentPath")}
          </Text>
          <ActionIcon
            aria-label={t("refresh")}
            loading={state.isRefreshing}
            variant="subtle"
            onClick={picker.refresh}
          >
            <IconRefresh size={rem(16)} />
          </ActionIcon>
        </Group>
        <Text ff="monospace" size="sm" truncate title={state.currentPath}>
          {state.currentPath}
        </Text>
        <ScrollArea.Autosize mah={rem(300)} type="auto">
          <Stack gap={rem(4)}>
            {parent ? (
              <UnstyledButton
                px="xs"
                py={rem(6)}
                onClick={() => picker.openDirectory(parent)}
              >
                <Group gap="xs" wrap="nowrap">
                  <IconChevronRight size={rem(15)} />
                  <Text ff="monospace" size="sm">
                    ../
                  </Text>
                </Group>
              </UnstyledButton>
            ) : null}
            {directories.map((entry) => (
              <UnstyledButton
                key={entry.path}
                px="xs"
                py={rem(6)}
                onClick={() => picker.openDirectory(entry.path)}
              >
                <Group gap="xs" wrap="nowrap" miw={0}>
                  <IconFolder
                    color="var(--mantine-color-blue-6)"
                    size={rem(16)}
                  />
                  <Text ff="monospace" size="sm" truncate title={entry.path}>
                    {entry.path}
                  </Text>
                  <IconChevronRight size={rem(15)} />
                </Group>
              </UnstyledButton>
            ))}
            {directories.length === 0 ? (
              <Text c="dimmed" size="sm">
                {t("upload.noDirectories")}
              </Text>
            ) : null}
          </Stack>
        </ScrollArea.Autosize>
        <Button
          fullWidth
          variant="light"
          onClick={() =>
            picker.selectDirectory(currentDirectoryEntry(state.currentPath))
          }
        >
          {t("upload.useOpenDirectory", { path: state.currentPath })}
        </Button>
      </Stack>
    );
  };

  return (
    <Modal
      centered
      data-testid="workspace-upload-destination-picker"
      opened={picker.isOpen}
      size="lg"
      title={t("upload.destinationTitle")}
      onClose={picker.close}
    >
      {renderContent()}
    </Modal>
  );
}
