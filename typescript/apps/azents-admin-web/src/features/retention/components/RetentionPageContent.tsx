"use client";

import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Radio,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconArchive, IconCheck } from "@tabler/icons-react";
import type { RetentionPageContentProps } from "../containers/useRetentionPageContainer";
import type {
  RetentionApplicationScope,
  RetentionApplicationState,
  RetentionSettingsState,
  RetentionUpdateConfirmation,
} from "../types";

function isApplicationScope(value: string): value is RetentionApplicationScope {
  return value === "new_archives_only" || value === "recalculate_existing";
}

function formatRetention(retentionDays: number | null): string {
  if (retentionDays === null) {
    return "Unlimited";
  }
  return retentionDays === 1 ? "1 day" : `${retentionDays} days`;
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat([], {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function ConfirmationSummary({
  confirmation,
}: {
  confirmation: RetentionUpdateConfirmation;
}): React.ReactElement {
  const rows = [
    { label: "Archives affected", value: confirmation.preview.affected_count },
    {
      label: "Immediately eligible",
      value: confirmation.preview.immediately_eligible_count,
    },
    {
      label: "Purge jobs scheduled",
      value: confirmation.preview.scheduled_count,
    },
    {
      label: "Purge jobs cancelled",
      value: confirmation.preview.cancelled_count,
    },
    {
      label: "Already fencing and excluded",
      value: confirmation.preview.excluded_count,
    },
  ];

  return (
    <Stack gap="md">
      <Alert color="orange" title="Existing deadlines will change">
        The new {formatRetention(confirmation.retentionDays)} policy will be
        applied asynchronously. Overdue archives become eligible for the next
        five-minute purge pass.
      </Alert>
      <Table withTableBorder withRowBorders>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.label}>
              <Table.Th>{row.label}</Table.Th>
              <Table.Td ta="right">{row.value}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

interface SettingsPanelProps {
  state: RetentionSettingsState;
  retentionDays: number | null;
  applicationScope: RetentionApplicationScope;
  previewing: boolean;
  saving: boolean;
  saveDisabled: boolean;
  onRetentionDaysChange: (retentionDays: number | null) => void;
  onApplicationScopeChange: (scope: RetentionApplicationScope) => void;
  onSave: () => void;
}

function SettingsPanel({
  state,
  retentionDays,
  applicationScope,
  previewing,
  saving,
  saveDisabled,
  onRetentionDaysChange,
  onApplicationScopeChange,
  onSave,
}: SettingsPanelProps): React.ReactElement {
  switch (state.type) {
    case "LOADING":
      return (
        <Group justify="center" p="xl">
          <Loader />
        </Group>
      );
    case "ERROR":
      return (
        <Alert
          color="red"
          icon={<IconAlertTriangle size={16} />}
          title="Unable to load retention settings"
        >
          {state.message}
        </Alert>
      );
    case "LOADED":
      return (
        <Paper withBorder p="lg" radius="md">
          <Stack gap="lg">
            <Group justify="space-between" align="flex-start">
              <Stack gap={2}>
                <Text fw={700}>Retention policy</Text>
                <Text size="sm" c="dimmed">
                  Current policy:{" "}
                  {formatRetention(
                    state.settings.archived_session_retention_days,
                  )}
                </Text>
              </Stack>
              <Badge variant="light">Revision {state.settings.revision}</Badge>
            </Group>

            <Switch
              label="Unlimited retention"
              description="Archived sessions remain restorable until an administrator applies a finite policy."
              checked={retentionDays === null}
              onChange={(event) =>
                onRetentionDaysChange(event.currentTarget.checked ? null : 30)
              }
            />

            <NumberInput
              label="Retention days"
              description="Whole days. Zero makes an archive eligible for a later scheduler purge pass; saving never deletes synchronously."
              min={0}
              allowDecimal={false}
              value={retentionDays ?? ""}
              disabled={retentionDays === null}
              onChange={(value) => {
                if (typeof value === "number") {
                  onRetentionDaysChange(value);
                }
              }}
            />

            <Divider />

            <Radio.Group
              label="Apply this revision to"
              value={applicationScope}
              onChange={(value) => {
                if (isApplicationScope(value)) {
                  onApplicationScopeChange(value);
                }
              }}
            >
              <Stack mt="sm" gap="sm">
                <Radio
                  value="new_archives_only"
                  label="New archives only"
                  description="Keep existing archive deadlines unchanged."
                />
                <Radio
                  value="recalculate_existing"
                  label="Recalculate existing archives"
                  description="Preview and asynchronously update every archive that has not entered purge fencing."
                />
              </Stack>
            </Radio.Group>

            <Group justify="space-between" align="flex-end">
              <Text size="xs" c="dimmed">
                Last updated {formatTimestamp(state.settings.updated_at)}
                {state.settings.updated_by_user_id
                  ? ` by ${state.settings.updated_by_user_id}`
                  : ""}
              </Text>
              <Button
                loading={previewing || saving}
                disabled={saveDisabled}
                onClick={onSave}
              >
                Save retention policy
              </Button>
            </Group>
          </Stack>
        </Paper>
      );
  }
}

function getApplicationStatusDescription(
  applicationState: Extract<RetentionApplicationState, { type: "LOADED" }>,
): string {
  const application = applicationState.application;
  switch (application.status) {
    case "pending":
      return "Waiting for the next recalculation worker pass.";
    case "running":
      return "A bounded archive batch is being recalculated.";
    case "retry_wait":
      return application.next_attempt_at
        ? `Retry scheduled for ${formatTimestamp(application.next_attempt_at)}.`
        : "The recalculation is waiting to retry.";
    case "completed":
      return application.completed_at
        ? `Completed ${formatTimestamp(application.completed_at)}.`
        : "Recalculation completed.";
  }
}

function ApplicationPanel({
  state,
}: {
  state: RetentionApplicationState;
}): React.ReactElement | null {
  switch (state.type) {
    case "IDLE":
      return null;
    case "LOADING":
      return (
        <Paper withBorder p="md">
          <Group gap="sm">
            <Loader size="sm" />
            <Text size="sm">Loading recalculation progress…</Text>
          </Group>
        </Paper>
      );
    case "ERROR":
      return (
        <Alert color="red" title="Unable to load recalculation progress">
          {state.message}
        </Alert>
      );
    case "LOADED": {
      const application = state.application;
      const completed = application.status === "completed";
      const processedCount =
        application.affected_count + application.skipped_count;
      return (
        <Paper withBorder p="lg" radius="md">
          <Stack gap="md">
            <Group justify="space-between" align="flex-start">
              <Stack gap={2}>
                <Text fw={700}>Existing archive recalculation</Text>
                <Text size="xs" c="dimmed">
                  Application {application.id}
                </Text>
              </Stack>
              <Badge
                color={
                  completed
                    ? "green"
                    : application.status === "retry_wait"
                      ? "orange"
                      : "blue"
                }
              >
                {application.status.replace("_", " ")}
              </Badge>
            </Group>
            <Group gap="sm" wrap="nowrap">
              {completed ? (
                <IconCheck color="var(--mantine-color-green-6)" size={18} />
              ) : (
                <Loader size="sm" />
              )}
              <Text size="sm">{getApplicationStatusDescription(state)}</Text>
            </Group>
            <Table withRowBorders>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Th>Processed roots</Table.Th>
                  <Table.Td ta="right">{processedCount}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Affected</Table.Th>
                  <Table.Td ta="right">{application.affected_count}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Immediately eligible</Table.Th>
                  <Table.Td ta="right">
                    {application.immediately_eligible_count}
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Scheduled</Table.Th>
                  <Table.Td ta="right">{application.scheduled_count}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Cancelled</Table.Th>
                  <Table.Td ta="right">{application.cancelled_count}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Skipped after fencing</Table.Th>
                  <Table.Td ta="right">{application.skipped_count}</Table.Td>
                </Table.Tr>
              </Table.Tbody>
            </Table>
            {application.last_error_summary && (
              <Alert color="orange" title="Recalculation will retry">
                {application.last_error_summary}
              </Alert>
            )}
          </Stack>
        </Paper>
      );
    }
  }
}

export function RetentionPageContent({
  state,
  retentionDays,
  applicationScope,
  confirmation,
  applicationState,
  previewing,
  saving,
  saveDisabled,
  errorMessage,
  successMessage,
  onRetentionDaysChange,
  onApplicationScopeChange,
  onSave,
  onCancelConfirmation,
  onConfirmUpdate,
}: RetentionPageContentProps): React.ReactElement {
  return (
    <Stack gap="lg" p="md" maw="60rem">
      <Stack gap={4}>
        <Group gap="sm">
          <IconArchive size={24} />
          <Title order={2}>Archived session retention</Title>
        </Group>
        <Text c="dimmed">
          Control how long archived session trees and their owned files remain
          restorable before asynchronous deletion.
        </Text>
      </Stack>

      {errorMessage && (
        <Alert color="red" title="Retention update failed">
          {errorMessage}
        </Alert>
      )}

      {successMessage && (
        <Alert color="green" icon={<IconCheck size={16} />}>
          {successMessage}
        </Alert>
      )}

      <SettingsPanel
        state={state}
        retentionDays={retentionDays}
        applicationScope={applicationScope}
        previewing={previewing}
        saving={saving}
        saveDisabled={saveDisabled}
        onRetentionDaysChange={onRetentionDaysChange}
        onApplicationScopeChange={onApplicationScopeChange}
        onSave={onSave}
      />

      <ApplicationPanel state={applicationState} />

      <Modal
        opened={confirmation !== null}
        onClose={onCancelConfirmation}
        title="Recalculate existing archive deadlines?"
        centered
      >
        {confirmation && <ConfirmationSummary confirmation={confirmation} />}
        <Group justify="flex-end" mt="lg">
          <Button variant="default" onClick={onCancelConfirmation}>
            Cancel
          </Button>
          <Button color="orange" loading={saving} onClick={onConfirmUpdate}>
            Apply to existing archives
          </Button>
        </Group>
      </Modal>
    </Stack>
  );
}
