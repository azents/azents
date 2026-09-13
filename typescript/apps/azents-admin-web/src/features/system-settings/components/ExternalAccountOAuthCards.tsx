"use client";

import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  CopyButton,
  Group,
  Loader,
  Paper,
  PasswordInput,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconCopy,
  IconHeartbeat,
} from "@tabler/icons-react";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useExternalAccountOAuthCardsContainer } from "../containers/useExternalAccountOAuthCardsContainer";
import type {
  ExternalAccountOAuthCardContainerProps,
  ExternalAccountOAuthCardsContainerProps,
  ExternalAccountOAuthCardState,
} from "../containers/useExternalAccountOAuthCardsContainer";
import type {
  ExternalAccountOAuthDetailResponse,
  ExternalAccountOAuthFieldResponse,
} from "@azents/admin-client";

function titleCase(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function statusColor(status: string): string {
  switch (status) {
    case "ready":
    case "healthy":
      return "green";
    case "not_configured":
      return "gray";
    case "incomplete":
      return "yellow";
    case "invalid":
      return "red";
    case "unavailable":
      return "orange";
    default:
      return "gray";
  }
}

function findField(
  detail: ExternalAccountOAuthDetailResponse,
  name: string,
): ExternalAccountOAuthFieldResponse | null {
  return detail.fields.find((field) => field.name === name) ?? null;
}

function fieldStatus(
  field: ExternalAccountOAuthFieldResponse,
): React.ReactNode {
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
    </Group>
  );
}

function ExternalAccountOAuthCard({
  config,
  state,
}: ExternalAccountOAuthCardContainerProps): React.ReactElement {
  if (state.type === "LOADING") {
    return (
      <Paper withBorder p="lg" radius="md">
        <Loader size="sm" />
      </Paper>
    );
  }

  if (state.type === "ERROR") {
    return (
      <Paper withBorder p="lg" radius="md">
        <Alert color="red" title={`Unable to load ${config.title}`}>
          {state.message}
        </Alert>
      </Paper>
    );
  }

  return <LoadedExternalAccountOAuthCard config={config} state={state} />;
}

function LoadedExternalAccountOAuthCard({
  config,
  state,
}: {
  config: ExternalAccountOAuthCardContainerProps["config"];
  state: Extract<ExternalAccountOAuthCardState, { type: "LOADED" }>;
}): React.ReactElement {
  const clientField = findField(state.detail, config.clientField);
  const secretField = findField(state.detail, "client_secret");
  const Icon = config.Icon;

  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="lg">
        <Group justify="space-between" align="flex-start">
          <Group gap="sm" wrap="nowrap">
            <Icon size={22} />
            <Stack gap={2}>
              <Text fw={700}>{config.title}</Text>
              <Text size="sm" c="dimmed">
                {config.description}
              </Text>
            </Stack>
          </Group>
          <Badge
            color={statusColor(state.detail.effective_status)}
            variant="light"
          >
            {titleCase(state.detail.effective_status)}
          </Badge>
        </Group>

        {state.mutationError ? (
          <Alert color="red" icon={<IconAlertTriangle size={16} />}>
            {state.mutationError}
          </Alert>
        ) : null}

        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
          <Stack gap={4}>
            <TextInput
              label={config.clientLabel}
              value={state.draft.clientValue}
              disabled={clientField?.source === "environment"}
              onChange={(event) => {
                const value = event.currentTarget.value;
                state.onClientValueChange(value);
              }}
            />
            {clientField ? fieldStatus(clientField) : null}
          </Stack>
          <Stack gap="xs">
            <PasswordInput
              label="Client secret replacement"
              description="Existing plaintext is never returned. Leave empty to keep the current secret."
              value={state.draft.clientSecret}
              disabled={
                secretField?.source === "environment" ||
                state.draft.clearClientSecret
              }
              onChange={(event) => {
                const value = event.currentTarget.value;
                state.onClientSecretChange(value);
              }}
            />
            {secretField ? fieldStatus(secretField) : null}
            <Checkbox
              label="Clear stored client secret"
              checked={state.draft.clearClientSecret}
              disabled={secretField?.source === "environment"}
              onChange={(event) => {
                const checked = event.currentTarget.checked;
                state.onClearClientSecretChange(checked);
              }}
            />
          </Stack>
        </SimpleGrid>

        <Stack gap="xs">
          <Text size="sm" fw={600}>
            Registered callback URL
          </Text>
          <Group gap="xs" align="center" wrap="nowrap">
            <Code style={{ overflowWrap: "anywhere" }}>
              {state.detail.callback_url ??
                "Unavailable until the public Web URL is configured."}
            </Code>
            {state.detail.callback_url ? (
              <CopyButton value={state.detail.callback_url}>
                {({ copied, copy }) => (
                  <Button
                    variant="subtle"
                    size="compact-xs"
                    leftSection={
                      copied ? <IconCheck size={14} /> : <IconCopy size={14} />
                    }
                    onClick={copy}
                  >
                    {copied ? "Copied" : "Copy"}
                  </Button>
                )}
              </CopyButton>
            ) : null}
          </Group>
          <Text size="xs" c="dimmed">
            Register this exact URL in the {config.provider} provider
            application. It is fixed by the server and cannot be supplied by a
            caller.
          </Text>
        </Stack>

        <Group justify="space-between" align="flex-end" wrap="wrap">
          <Stack gap={4}>
            <Text size="xs" c="dimmed">
              Admin version {state.detail.admin_version}. Changes are applied
              optimistically and recorded in the metadata-only audit log.
            </Text>
            {state.detail.health ? (
              <Alert
                color={statusColor(state.detail.health.status)}
                icon={
                  state.detail.health.status === "healthy" ? (
                    <IconCheck size={16} />
                  ) : (
                    <IconAlertTriangle size={16} />
                  )
                }
                title={`${titleCase(state.detail.health.status)} · ${state.detail.health.checked_at}`}
              >
                {state.detail.health.message ?? state.detail.health.action_hint}
              </Alert>
            ) : null}
          </Stack>
          <Group gap="xs">
            <Button
              variant="light"
              leftSection={<IconHeartbeat size={16} />}
              loading={state.checkingHealth}
              onClick={state.onCheckHealth}
            >
              Check health
            </Button>
            <Button
              loading={state.saving}
              disabled={!state.dirty}
              onClick={state.onSave}
            >
              Save OAuth settings
            </Button>
          </Group>
        </Group>
      </Stack>
    </Paper>
  );
}

function ExternalAccountOAuthCardsView({
  cards,
}: ExternalAccountOAuthCardsContainerProps): React.ReactElement {
  return (
    <Stack gap="md">
      <Stack gap={2}>
        <Text fw={700} size="lg">
          External account authorization
        </Text>
        <Text size="sm" c="dimmed">
          Manage the independent Slack and Discord OAuth applications used for
          User identity linking. Provider secrets are write-only and never
          displayed.
        </Text>
      </Stack>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        {cards.map((card) => (
          <ExternalAccountOAuthCard key={card.config.provider} {...card} />
        ))}
      </SimpleGrid>
    </Stack>
  );
}

export const ExternalAccountOAuthCards = createReactContainer(
  "ExternalAccountOAuthCards",
  useExternalAccountOAuthCardsContainer,
  ExternalAccountOAuthCardsView,
);
