"use client";

import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  Group,
  Loader,
  Paper,
  ScrollArea,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { canAllowWorkspaceRuntimeExecutionProfile } from "../runtimeExecutionPresentation";
import { RuntimeExecutionRestrictionEditor } from "./RuntimeExecutionRestrictionEditor";
import type { WorkspaceRuntimeExecutionProps } from "../types";
import type {
  RuntimeExecutionAvailabilityReason,
  WorkspaceRuntimeExecutionProfileResponse,
} from "@azents/public-client";

function ProfilePolicySummary({
  profile,
}: {
  profile: WorkspaceRuntimeExecutionProfileResponse;
}): React.ReactElement {
  return (
    <Group gap="xs">
      <Badge
        color={profile.policy.docker.enabled ? "blue" : "gray"}
        variant="light"
      >
        Docker
      </Badge>
      <Badge variant="outline">{profile.policy.docker.storage_mode}</Badge>
    </Group>
  );
}

export function WorkspaceRuntimeExecution({
  state,
  restriction,
  allowedProfileIds,
  saving,
  canSave,
  hasUnsupportedSelection,
  actionError,
  onRestrictionChange,
  onToggleProfile,
  onSave,
}: WorkspaceRuntimeExecutionProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.workspacePage");

  const reasonLabel = (reason: RuntimeExecutionAvailabilityReason): string => {
    switch (reason) {
      case "profile_retired":
        return t("reasons.profile_retired");
      case "profile_not_allowed":
        return t("reasons.profile_not_allowed");
      case "dependency_unsatisfied":
        return t("reasons.dependency_unsatisfied");
      case "provider_module_unsupported":
        return t("reasons.provider_module_unsupported");
      case "provider_storage_unsupported":
        return t("reasons.provider_storage_unsupported");
      case "provider_limit_exceeded":
        return t("reasons.provider_limit_exceeded");
    }
  };

  return (
    <ScrollArea h="100%">
      <Stack gap="xl" p="md" maw="75rem" mx="auto">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Title order={2}>{t("title")}</Title>
            <Text c="dimmed">{t("description")}</Text>
          </Stack>
          {state.type === "LOADED" && state.canEdit && (
            <Button loading={saving} disabled={!canSave} onClick={onSave}>
              {t("save")}
            </Button>
          )}
        </Group>
        {actionError && (
          <Alert color="red" title={t("actionFailed")}>
            {actionError}
          </Alert>
        )}
        {state.type === "LOADING" && <Loader />}
        {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
        {state.type === "LOADED" && (
          <>
            {!state.canEdit && <Alert color="blue">{t("readOnly")}</Alert>}
            <Paper withBorder p="md" radius="md">
              <Group justify="space-between" align="flex-start">
                <Stack gap={3}>
                  <Text fw={600}>{t("allowedProfiles")}</Text>
                  <Text size="sm" c="dimmed">
                    {t("allowedDescription")}
                  </Text>
                  {hasUnsupportedSelection && (
                    <Alert color="yellow">{t("unsupportedSelection")}</Alert>
                  )}
                </Stack>
                <Stack gap={2} align="flex-end">
                  <Text size="xs" c="dimmed">
                    {t("version", { version: state.policy.version })}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t("digest", {
                      digest: state.policy.digest.slice(0, 16),
                    })}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {state.policy.updated_at
                      ? t("updated", {
                          time: new Date(
                            state.policy.updated_at,
                          ).toLocaleString(),
                        })
                      : t("neverUpdated")}
                  </Text>
                </Stack>
              </Group>
              <Stack gap="sm" mt="md">
                {state.profiles.length === 0 && (
                  <Alert color="yellow">{t("noProfiles")}</Alert>
                )}
                {state.profiles.map((profile) => {
                  const allowed = allowedProfileIds.includes(profile.id);
                  const canAllow = canAllowWorkspaceRuntimeExecutionProfile(
                    profile,
                    state.policy.capabilities,
                  );
                  return (
                    <Paper key={profile.id} withBorder p="sm" radius="sm">
                      <Group
                        justify="space-between"
                        align="flex-start"
                        wrap="nowrap"
                      >
                        <Group align="flex-start" wrap="nowrap">
                          <Checkbox
                            mt="xs"
                            checked={allowed}
                            disabled={!state.canEdit || (!allowed && !canAllow)}
                            aria-label={`${profile.display_name}: ${t("allowed")}`}
                            onChange={(event) =>
                              onToggleProfile(
                                profile.id,
                                event.currentTarget.checked,
                              )
                            }
                          />
                          <Stack gap={4}>
                            <Group gap="xs">
                              <Text fw={600}>{profile.display_name}</Text>
                              <Badge
                                color={allowed ? "blue" : "gray"}
                                variant="light"
                              >
                                {allowed ? t("allowed") : t("blocked")}
                              </Badge>
                              <Badge
                                color={profile.available ? "green" : "yellow"}
                                variant="light"
                              >
                                {profile.available
                                  ? t("available")
                                  : t("unavailable")}
                              </Badge>
                            </Group>
                            <Text size="sm" c="dimmed">
                              {profile.description}
                            </Text>
                            <ProfilePolicySummary profile={profile} />
                          </Stack>
                        </Group>
                        <Stack gap={3} align="flex-end">
                          <Code>{profile.id}</Code>
                          <Text size="xs" c="dimmed">
                            v{profile.version}
                          </Text>
                          {profile.reason && (
                            <Text size="xs" c="yellow">
                              {reasonLabel(profile.reason)}
                            </Text>
                          )}
                        </Stack>
                      </Group>
                    </Paper>
                  );
                })}
              </Stack>
            </Paper>

            <Stack gap="sm">
              <Text fw={600}>{t("restrictionsTitle")}</Text>
              {restriction && (
                <RuntimeExecutionRestrictionEditor
                  restriction={restriction}
                  readOnly={!state.canEdit}
                  onChange={onRestrictionChange}
                />
              )}
            </Stack>

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
