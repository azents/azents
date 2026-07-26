"use client";

import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { AgentRuntimePolicyStatus } from "./AgentRuntimePolicyStatus";
import { RuntimeExecutionRestrictionEditor } from "./RuntimeExecutionRestrictionEditor";
import type { AgentRuntimeExecutionProps } from "../types";

export function AgentRuntimeExecution({
  state,
  statusState,
  profileId,
  restriction,
  saving,
  applying,
  canSave,
  actionError,
  actionMessage,
  onProfileChange,
  onRestrictionChange,
  onSave,
  onApply,
}: AgentRuntimeExecutionProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.agentPage");

  return (
    <ScrollArea h="100%">
      <Stack gap="xl" p="md" maw="75rem" mx="auto">
        <Stack gap={4}>
          <Title order={2}>{t("title")}</Title>
          <Text c="dimmed">{t("description")}</Text>
        </Stack>
        {actionError && (
          <Alert color="red" title={t("actionFailed")}>
            {actionError}
          </Alert>
        )}
        {actionMessage === "saved" && (
          <Alert color="blue">{t("saveSuccess")}</Alert>
        )}
        {actionMessage === "applied" && (
          <Alert color="green">{t("applySuccess")}</Alert>
        )}
        <AgentRuntimePolicyStatus
          state={statusState}
          applying={applying}
          onApply={onApply}
        />
        {state.type === "LOADING" && <Loader />}
        {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
        {state.type === "LOADED" && (
          <>
            <Paper withBorder p="md" radius="md">
              <Stack gap="md">
                <Group justify="space-between" align="flex-start">
                  <Stack gap={3}>
                    <Text fw={600}>{t("configurationTitle")}</Text>
                    <Text size="sm" c="dimmed">
                      {t("configurationDescription")}
                    </Text>
                  </Stack>
                  <Button loading={saving} disabled={!canSave} onClick={onSave}>
                    {t("save")}
                  </Button>
                </Group>
                <Select
                  label={t("profile")}
                  value={profileId}
                  allowDeselect={false}
                  data={state.profiles.map((profile) => ({
                    value: profile.id,
                    label: `${profile.display_name}${
                      profile.lifecycle === "retired"
                        ? ` · ${t("profileRetired")}`
                        : !profile.available
                          ? ` · ${t("profileUnavailable")}`
                          : ""
                    }`,
                    disabled:
                      profile.lifecycle === "retired" || !profile.available,
                  }))}
                  onChange={(value) => {
                    if (value !== null) {
                      onProfileChange(value);
                    }
                  }}
                />
                <Group gap="xs">
                  <Badge variant="light">v{state.policy.profile_version}</Badge>
                  <Code>{state.policy.digest.slice(0, 16)}</Code>
                  <Badge
                    color={
                      state.policy.effective_preview.available
                        ? "green"
                        : "yellow"
                    }
                    variant="light"
                  >
                    {state.policy.effective_preview.available
                      ? "available"
                      : state.policy.effective_preview.availability_reason}
                  </Badge>
                </Group>
                {!state.policy.provider_compatibility_evaluated && (
                  <Alert color="blue">{t("providerCompatibility")}</Alert>
                )}
              </Stack>
            </Paper>

            <Stack gap="sm">
              <Text fw={600}>{t("reductions")}</Text>
              {state.policy.effective_preview.reductions.length === 0 ? (
                <Alert color="blue">{t("noReductions")}</Alert>
              ) : (
                <SimpleGrid cols={{ base: 1, lg: 2 }}>
                  {state.policy.effective_preview.reductions.map(
                    (reduction) => (
                      <Paper key={reduction.path} withBorder p="sm" radius="md">
                        <Stack gap={3}>
                          <Code>{reduction.path}</Code>
                          <Text size="sm">
                            {JSON.stringify(reduction.previous)} →{" "}
                            {JSON.stringify(reduction.current)}
                          </Text>
                          <Badge variant="light">
                            {reduction.governing_layer}
                          </Badge>
                        </Stack>
                      </Paper>
                    ),
                  )}
                </SimpleGrid>
              )}
            </Stack>

            {restriction && (
              <RuntimeExecutionRestrictionEditor
                restriction={restriction}
                onChange={onRestrictionChange}
              />
            )}

            <Stack gap="sm">
              <Text fw={600}>{t("auditTitle")}</Text>
              {state.auditEvents.length === 0 && (
                <Alert color="yellow">{t("noAudit")}</Alert>
              )}
              <SimpleGrid cols={{ base: 1, lg: 2 }}>
                {state.auditEvents.map((event) => (
                  <Paper key={event.id} withBorder p="md" radius="md">
                    <Stack gap={4}>
                      <Group justify="space-between">
                        <Badge variant="light">{event.classification}</Badge>
                        <Text size="xs" c="dimmed">
                          {new Date(event.created_at).toLocaleString()}
                        </Text>
                      </Group>
                      <Text fw={600}>{event.event_type}</Text>
                      <Text size="sm" c="dimmed">
                        {event.reason_code} → {event.outcome_code}
                      </Text>
                      <Text size="xs" ff="monospace">
                        {event.changed_paths.join(", ") || "metadata"}
                      </Text>
                    </Stack>
                  </Paper>
                ))}
              </SimpleGrid>
            </Stack>
          </>
        )}
      </Stack>
    </ScrollArea>
  );
}
