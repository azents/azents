"use client";

import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  Progress,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconCheck, IconRefresh, IconUpload, IconX } from "@tabler/icons-react";
import type { WorkspacePanelTranslator } from "../containers/useWorkspacePanelTranslations";
import type { WorkspaceUploadRow } from "../workspaceUploadTypes";
import type { WorkspaceUploadFailure } from "@azents/public-client";

export interface WorkspaceUploadPanelProps {
  rows: WorkspaceUploadRow[];
  t: WorkspacePanelTranslator;
  onCancel: (id: string) => void;
  onRetry: (id: string, overwrite: boolean) => void;
  onDismiss: (id: string) => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function phaseLabel(
  phase: WorkspaceUploadRow["phase"],
  t: WorkspacePanelTranslator,
): string {
  switch (phase) {
    case "queued":
      return t("upload.phases.queued");
    case "hashing":
      return t("upload.phases.hashing");
    case "uploading":
      return t("upload.phases.uploading");
    case "moving_to_runtime":
      return t("upload.phases.movingToRuntime");
    case "succeeded":
      return t("upload.phases.succeeded");
    case "cancelled":
      return t("upload.phases.cancelled");
    case "conflicted":
      return t("upload.phases.conflicted");
    case "failed":
      return t("upload.phases.failed");
  }
}

function phaseColor(phase: WorkspaceUploadRow["phase"]): string {
  switch (phase) {
    case "succeeded":
      return "green";
    case "cancelled":
      return "gray";
    case "conflicted":
      return "orange";
    case "failed":
      return "red";
    default:
      return "blue";
  }
}

function failureLabel(
  failure: WorkspaceUploadFailure | null,
  t: WorkspacePanelTranslator,
): string | null {
  if (!failure) {
    return null;
  }
  switch (failure) {
    case "invalid_request":
      return t("upload.failures.invalidRequest");
    case "authorization":
      return t("upload.failures.authorization");
    case "too_large":
      return t("upload.failures.tooLarge");
    case "revision_conflict":
      return t("upload.failures.revisionConflict");
    case "destination_conflict":
      return t("upload.failures.destinationConflict");
    case "runtime_unavailable":
      return t("upload.failures.runtimeUnavailable");
    case "fenced":
      return t("upload.failures.fenced");
    case "integrity":
      return t("upload.failures.integrity");
    case "transfer":
      return t("upload.failures.transfer");
    case "cancelled":
      return t("upload.failures.cancelled");
    case "expired":
      return t("upload.failures.expired");
  }
}

function isActive(phase: WorkspaceUploadRow["phase"]): boolean {
  return (
    phase === "hashing" ||
    phase === "uploading" ||
    phase === "moving_to_runtime"
  );
}

export function WorkspaceUploadPanel({
  rows,
  t,
  onCancel,
  onRetry,
  onDismiss,
}: WorkspaceUploadPanelProps): React.ReactElement | null {
  if (rows.length === 0) {
    return null;
  }

  const activeCount = rows.filter((row) => isActive(row.phase)).length;
  return (
    <Box
      px="xs"
      py="xs"
      style={{
        background: "var(--mantine-color-default-hover)",
        borderBottom: "1px solid var(--mantine-color-default-border)",
      }}
      data-testid="workspace-upload-panel"
    >
      <Group justify="space-between" gap="xs" mb="xs">
        <Group gap="xs">
          <IconUpload size="0.875rem" />
          <Text size="xs" fw={700}>
            {t("upload.title")}
          </Text>
          {activeCount > 0 ? (
            <Badge size="xs" variant="light" color="blue">
              {t("upload.activeCount", { count: activeCount })}
            </Badge>
          ) : null}
        </Group>
        <Text size="xs" c="dimmed">
          {t("upload.fileCount", { count: rows.length })}
        </Text>
      </Group>
      <ScrollArea.Autosize mah="14rem" offsetScrollbars>
        <Stack gap="xs">
          {rows.map((row) => {
            const failure = failureLabel(row.failure, t);
            const active = isActive(row.phase);
            return (
              <Paper key={row.id} withBorder p="xs" radius="md">
                <Stack gap="xs">
                  <Group justify="space-between" gap="xs" wrap="nowrap">
                    <Stack gap={0} miw={0} style={{ flex: "1 1 auto" }}>
                      <Text size="xs" fw={600} truncate title={row.filename}>
                        {row.filename}
                      </Text>
                      <Text
                        size="xs"
                        c="dimmed"
                        ff="monospace"
                        truncate
                        title={row.destinationPath}
                      >
                        {row.destinationPath}
                      </Text>
                    </Stack>
                    <Badge
                      size="xs"
                      color={phaseColor(row.phase)}
                      variant="light"
                    >
                      {phaseLabel(row.phase, t)}
                    </Badge>
                  </Group>
                  <Group justify="space-between" gap="xs">
                    <Text size="xs" c="dimmed">
                      {formatBytes(row.transferredBytes)} /{" "}
                      {formatBytes(row.expectedSize)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {row.progress}%
                    </Text>
                  </Group>
                  <Progress
                    size="xs"
                    value={row.progress}
                    color={phaseColor(row.phase)}
                    aria-label={t("upload.progress", { name: row.filename })}
                  />
                  {failure || row.errorMessage ? (
                    <Text size="xs" c="red">
                      {row.errorMessage ??
                        failure ??
                        t("upload.failedDescription")}
                    </Text>
                  ) : null}
                  <Group justify="flex-end" gap="xs">
                    {active ? (
                      <Button
                        size="xs"
                        variant="subtle"
                        color="gray"
                        leftSection={<IconX size="0.875rem" />}
                        onClick={() => onCancel(row.id)}
                      >
                        {t("cancel")}
                      </Button>
                    ) : null}
                    {row.retryAvailable ? (
                      <Button
                        size="xs"
                        variant="light"
                        leftSection={<IconRefresh size="0.875rem" />}
                        onClick={() => onRetry(row.id, false)}
                      >
                        {t("upload.retry")}
                      </Button>
                    ) : null}
                    {row.overwriteAvailable ? (
                      <Button
                        size="xs"
                        color="orange"
                        variant="light"
                        onClick={() => onRetry(row.id, true)}
                      >
                        {t("upload.overwriteAndRetry")}
                      </Button>
                    ) : null}
                    {!active ? (
                      <Tooltip label={t("upload.dismiss")}>
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          aria-label={t("upload.dismiss")}
                          onClick={() => onDismiss(row.id)}
                        >
                          {row.phase === "succeeded" ? (
                            <IconCheck size="0.875rem" />
                          ) : (
                            <IconX size="0.875rem" />
                          )}
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                  </Group>
                </Stack>
              </Paper>
            );
          })}
        </Stack>
      </ScrollArea.Autosize>
    </Box>
  );
}
