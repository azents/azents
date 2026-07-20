"use client";

import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Divider,
  Group,
  Loader,
  Paper,
  PasswordInput,
  Radio,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconBrandGithub,
  IconCheck,
  IconHeartbeat,
  IconRefresh,
  IconSettings,
  IconX,
} from "@tabler/icons-react";
import type { SystemSettingsPageContentProps } from "../containers/useSystemSettingsPageContainer";
import type {
  PlatformGitHubAppCandidateResponse,
  PlatformGitHubAppDetailResponse,
  PlatformGitHubAppEffectiveStatus,
  PlatformGitHubAppFieldResponse,
  SystemSettingAuditEventResponse,
  SystemSettingHealthStatus,
  SystemSettingValidationStatus,
} from "@azents/admin-client";

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat([], {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function effectiveStatusColor(
  status: PlatformGitHubAppEffectiveStatus,
): string {
  switch (status) {
    case "ready":
      return "green";
    case "not_configured":
      return "gray";
    case "incomplete":
      return "yellow";
    case "invalid":
    case "reconnect_required":
      return "red";
    case "unavailable":
      return "orange";
  }
}

function validationStatusColor(status: SystemSettingValidationStatus): string {
  switch (status) {
    case "valid":
      return "green";
    case "pending":
      return "blue";
    case "invalid":
      return "red";
    case "unavailable":
      return "orange";
  }
}

function healthStatusColor(status: SystemSettingHealthStatus): string {
  switch (status) {
    case "healthy":
      return "green";
    case "invalid":
      return "red";
    case "unavailable":
      return "orange";
  }
}

function findField(
  detail: PlatformGitHubAppDetailResponse,
  name: string,
): PlatformGitHubAppFieldResponse | null {
  return detail.fields.find((field) => field.name === name) ?? null;
}

function FieldMetadata({
  field,
}: {
  field: PlatformGitHubAppFieldResponse | null;
}): React.ReactElement | null {
  if (!field) {
    return null;
  }
  return (
    <Group gap="xs" mt={4}>
      <Badge size="xs" variant="light">
        {titleCase(field.source)}
      </Badge>
      <Badge
        size="xs"
        color={field.configured ? "green" : "gray"}
        variant="outline"
      >
        {field.configured ? "Configured" : "Not configured"}
      </Badge>
      {field.fallback_configured && field.source === "environment" && (
        <Badge size="xs" color="yellow" variant="outline">
          Admin fallback stored
        </Badge>
      )}
      <Text size="xs" c="dimmed">
        {field.environment_variable}
      </Text>
    </Group>
  );
}

function impactNumber(
  candidate: PlatformGitHubAppCandidateResponse,
  name: string,
): number | null {
  const value = candidate.impact?.[name];
  return typeof value === "number" ? value : null;
}

function CandidatePanel({
  candidate,
  confirmationAction,
  confirmationActions,
  validating,
  confirming,
  cancelling,
  onConfirmationActionChange,
  onValidateCandidate,
  onConfirmCandidate,
  onCancelCandidate,
}: Pick<
  SystemSettingsPageContentProps,
  | "confirmationAction"
  | "confirmationActions"
  | "validating"
  | "confirming"
  | "cancelling"
  | "onConfirmationActionChange"
  | "onValidateCandidate"
  | "onConfirmCandidate"
  | "onCancelCandidate"
> & {
  candidate: PlatformGitHubAppCandidateResponse;
}): React.ReactElement {
  const impactRows = [
    ["Users", impactNumber(candidate, "affected_user_count")],
    ["Installations", impactNumber(candidate, "affected_installation_count")],
    ["Toolkits", impactNumber(candidate, "affected_toolkit_count")],
    ["Agents", impactNumber(candidate, "affected_agent_count")],
  ].filter((row): row is [string, number] => row[1] !== null);

  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={700}>Pending candidate</Text>
            <Text size="xs" c="dimmed">
              Candidate {candidate.id} · expires{" "}
              {formatTimestamp(candidate.expires_at)}
            </Text>
          </Stack>
          <Badge color={validationStatusColor(candidate.validation_status)}>
            {titleCase(candidate.validation_status)}
          </Badge>
        </Group>

        {(candidate.validation_message || candidate.action_hint) && (
          <Alert
            color={candidate.validation_status === "invalid" ? "red" : "orange"}
            title={candidate.validation_code ?? "Candidate validation"}
          >
            <Stack gap={4}>
              {candidate.validation_message && (
                <Text size="sm">{candidate.validation_message}</Text>
              )}
              {candidate.action_hint && (
                <Text size="sm">{candidate.action_hint}</Text>
              )}
            </Stack>
          </Alert>
        )}

        {impactRows.length > 0 && (
          <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
            {impactRows.map(([label, value]) => (
              <Paper key={label} withBorder p="sm">
                <Text size="xs" c="dimmed">
                  {label}
                </Text>
                <Text fw={700} size="lg">
                  {value}
                </Text>
              </Paper>
            ))}
          </SimpleGrid>
        )}

        {confirmationActions.length > 0 && (
          <Radio.Group
            label="Activation action"
            description="Confirm activation that changes the Platform GitHub App identity."
            value={confirmationAction ?? ""}
            onChange={onConfirmationActionChange}
          >
            <Stack gap="xs" mt="xs">
              {confirmationActions.map((action) => (
                <Radio key={action} value={action} label={titleCase(action)} />
              ))}
            </Stack>
          </Radio.Group>
        )}

        <Group justify="space-between">
          <Button
            variant="subtle"
            color="red"
            leftSection={<IconX size={16} />}
            loading={cancelling}
            onClick={onCancelCandidate}
          >
            Cancel candidate
          </Button>
          <Group>
            <Button
              variant="light"
              leftSection={<IconRefresh size={16} />}
              loading={validating}
              onClick={onValidateCandidate}
            >
              Validate again
            </Button>
            <Button
              color="orange"
              disabled={
                candidate.validation_status !== "valid" ||
                confirmationAction === null
              }
              loading={confirming}
              onClick={onConfirmCandidate}
            >
              Confirm and activate
            </Button>
          </Group>
        </Group>
      </Stack>
    </Paper>
  );
}

function AuditTable({
  events,
  total,
}: {
  events: SystemSettingAuditEventResponse[];
  total: number;
}): React.ReactElement {
  if (events.length === 0) {
    return <Text c="dimmed">No System Settings audit events yet.</Text>;
  }
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        Showing {events.length} of {total} metadata-only events.
      </Text>
      <Table.ScrollContainer minWidth="48rem">
        <Table striped highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Time</Table.Th>
              <Table.Th>Event</Table.Th>
              <Table.Th>Source</Table.Th>
              <Table.Th>Version</Table.Th>
              <Table.Th>Changed fields</Table.Th>
              <Table.Th>Validation</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {events.map((event) => (
              <Table.Tr key={event.id}>
                <Table.Td>{formatTimestamp(event.created_at)}</Table.Td>
                <Table.Td>{titleCase(event.event_type)}</Table.Td>
                <Table.Td>{titleCase(event.source)}</Table.Td>
                <Table.Td>
                  {event.previous_version ?? "—"} → {event.new_version ?? "—"}
                </Table.Td>
                <Table.Td>
                  {event.changed_fields.length > 0
                    ? event.changed_fields.join(", ")
                    : "—"}
                </Table.Td>
                <Table.Td>
                  {event.validation_status
                    ? titleCase(event.validation_status)
                    : "—"}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

export function SystemSettingsPageContent({
  state,
  auditState,
  draft,
  confirmationAction,
  confirmationActions,
  saving,
  validating,
  confirming,
  cancelling,
  checkingHealth,
  saveDisabled,
  mutationError,
  onAppIdChange,
  onClientIdChange,
  onPrivateKeyChange,
  onClientSecretChange,
  onClearPrivateKeyChange,
  onClearClientSecretChange,
  onConfirmationActionChange,
  onSaveCandidate,
  onValidateCandidate,
  onConfirmCandidate,
  onCancelCandidate,
  onCheckHealth,
}: SystemSettingsPageContentProps): React.ReactElement {
  if (state.type === "LOADING") {
    return (
      <Group justify="center" p="xl">
        <Loader />
      </Group>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="red" title="Unable to load System Settings">
        {state.message}
      </Alert>
    );
  }

  const detail = state.detail;
  const appIdField = findField(detail, "app_id");
  const clientIdField = findField(detail, "client_id");
  const privateKeyField = findField(detail, "private_key");
  const clientSecretField = findField(detail, "client_secret");

  return (
    <Stack gap="lg" p="md" maw="72rem">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Group gap="sm">
            <IconSettings size={24} />
            <Title order={2}>System Settings</Title>
          </Group>
          <Text c="dimmed">
            Manage instance-wide operational configuration with redacted secret
            state and deployment-environment ownership.
          </Text>
        </Stack>
        <Badge size="lg" color={effectiveStatusColor(detail.effective_status)}>
          {titleCase(detail.effective_status)}
        </Badge>
      </Group>

      {mutationError && (
        <Alert
          color="red"
          icon={<IconAlertTriangle size={16} />}
          title="System Settings operation failed"
        >
          {mutationError}
        </Alert>
      )}

      {detail.effective_status === "reconnect_required" && (
        <Alert color="red" title="GitHub reconnect is required">
          Existing Platform GitHub App toolkits are bound to a different App
          identity. Users must reconnect affected toolkits in Main Web.
        </Alert>
      )}

      <Paper withBorder p="lg" radius="md">
        <Stack gap="lg">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Group gap="xs">
                <IconBrandGithub size={20} />
                <Text fw={700}>Platform GitHub App</Text>
              </Group>
              <Text size="sm" c="dimmed">
                Current App slug: {detail.app_slug ?? "Not resolved"}
              </Text>
            </Stack>
            <Badge variant="light">Version {detail.admin_version}</Badge>
          </Group>

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
            <Stack gap={4}>
              <TextInput
                label="App ID"
                description="The durable GitHub App identity. Changing it may require toolkit reconnects."
                value={draft.appId}
                disabled={appIdField?.source === "environment"}
                onChange={(event) => onAppIdChange(event.currentTarget.value)}
              />
              <FieldMetadata field={appIdField} />
            </Stack>
            <Stack gap={4}>
              <TextInput
                label="Client ID"
                value={draft.clientId}
                disabled={clientIdField?.source === "environment"}
                onChange={(event) =>
                  onClientIdChange(event.currentTarget.value)
                }
              />
              <FieldMetadata field={clientIdField} />
            </Stack>
            <Stack gap="xs">
              <PasswordInput
                label="Private key replacement"
                description="Leave empty to keep the stored fallback. Existing plaintext is never returned."
                value={draft.privateKey}
                disabled={
                  privateKeyField?.source === "environment" ||
                  draft.clearPrivateKey
                }
                onChange={(event) =>
                  onPrivateKeyChange(event.currentTarget.value)
                }
              />
              <FieldMetadata field={privateKeyField} />
              <Checkbox
                label="Clear stored private key fallback"
                checked={draft.clearPrivateKey}
                disabled={privateKeyField?.source === "environment"}
                onChange={(event) =>
                  onClearPrivateKeyChange(event.currentTarget.checked)
                }
              />
            </Stack>
            <Stack gap="xs">
              <PasswordInput
                label="Client secret replacement"
                description="Leave empty to keep the stored fallback. Existing plaintext is never returned."
                value={draft.clientSecret}
                disabled={
                  clientSecretField?.source === "environment" ||
                  draft.clearClientSecret
                }
                onChange={(event) =>
                  onClientSecretChange(event.currentTarget.value)
                }
              />
              <FieldMetadata field={clientSecretField} />
              <Checkbox
                label="Clear stored client secret fallback"
                checked={draft.clearClientSecret}
                disabled={clientSecretField?.source === "environment"}
                onChange={(event) =>
                  onClearClientSecretChange(event.currentTarget.checked)
                }
              />
            </Stack>
          </SimpleGrid>

          <Divider />
          <Group justify="space-between" align="flex-end">
            <Text size="xs" c="dimmed">
              Saving creates and validates an atomic candidate. Environment
              fields remain permanent overlays, including explicit empty values.
            </Text>
            <Button
              loading={saving}
              disabled={saveDisabled}
              onClick={onSaveCandidate}
            >
              Save and validate candidate
            </Button>
          </Group>
        </Stack>
      </Paper>

      {detail.candidate && (
        <CandidatePanel
          candidate={detail.candidate}
          confirmationAction={confirmationAction}
          confirmationActions={confirmationActions}
          validating={validating}
          confirming={confirming}
          cancelling={cancelling}
          onConfirmationActionChange={onConfirmationActionChange}
          onValidateCandidate={onValidateCandidate}
          onConfirmCandidate={onConfirmCandidate}
          onCancelCandidate={onCancelCandidate}
        />
      )}

      <Paper withBorder p="lg" radius="md">
        <Stack gap="md">
          <Group justify="space-between">
            <Stack gap={2}>
              <Text fw={700}>Effective health</Text>
              <Text size="sm" c="dimmed">
                Runs an explicit check against the current effective App without
                exposing credentials.
              </Text>
            </Stack>
            <Button
              variant="light"
              leftSection={<IconHeartbeat size={16} />}
              loading={checkingHealth}
              onClick={onCheckHealth}
            >
              Check health
            </Button>
          </Group>
          {detail.health ? (
            <Alert
              color={healthStatusColor(detail.health.status)}
              icon={
                detail.health.status === "healthy" ? (
                  <IconCheck size={16} />
                ) : (
                  <IconAlertTriangle size={16} />
                )
              }
              title={`${titleCase(detail.health.status)} · ${formatTimestamp(detail.health.checked_at)}`}
            >
              <Stack gap={4}>
                {detail.health.message && (
                  <Text size="sm">{detail.health.message}</Text>
                )}
                {detail.health.action_hint && (
                  <Text size="sm">{detail.health.action_hint}</Text>
                )}
              </Stack>
            </Alert>
          ) : (
            <Text size="sm" c="dimmed">
              No explicit health check has been recorded.
            </Text>
          )}
        </Stack>
      </Paper>

      {detail.binding_impact && (
        <Paper withBorder p="lg" radius="md">
          <Stack gap="md">
            <Text fw={700}>Current reconnect impact</Text>
            <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
              {[
                ["Users", detail.binding_impact.affected_user_count],
                [
                  "Installations",
                  detail.binding_impact.affected_installation_count,
                ],
                ["Toolkits", detail.binding_impact.affected_toolkit_count],
                ["Agents", detail.binding_impact.affected_agent_count],
              ].map(([label, value]) => (
                <Paper key={label} withBorder p="sm">
                  <Text size="xs" c="dimmed">
                    {label}
                  </Text>
                  <Text fw={700} size="lg">
                    {value}
                  </Text>
                </Paper>
              ))}
            </SimpleGrid>
          </Stack>
        </Paper>
      )}

      <Paper withBorder p="lg" radius="md">
        <Stack gap="md">
          <Text fw={700}>Audit events</Text>
          {auditState.type === "LOADING" && <Loader size="sm" />}
          {auditState.type === "ERROR" && (
            <Alert color="red">{auditState.message}</Alert>
          )}
          {auditState.type === "LOADED" && (
            <AuditTable events={auditState.events} total={auditState.total} />
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}
