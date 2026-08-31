"use client";

import {
  Alert,
  Badge,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type { AgentRuntimeLifecyclePresentationResponse } from "@azents/public-client";

interface RuntimeLifecycleStatusProps {
  lifecycle: AgentRuntimeLifecyclePresentationResponse;
  compact?: boolean;
}

function availabilityColor(
  availability: AgentRuntimeLifecyclePresentationResponse["availability"],
): string {
  switch (availability) {
    case "ready":
      return "green";
    case "stopped":
      return "gray";
    case "transitioning":
      return "blue";
    case "provider_disconnected":
    case "runner_unavailable":
    case "configuration_blocked":
    case "removing":
      return "yellow";
    case "failed":
      return "red";
  }
}

function statusKey(
  lifecycle: AgentRuntimeLifecyclePresentationResponse,
):
  | "ready"
  | "stopped"
  | "starting"
  | "stopping"
  | "resetting"
  | "recovering"
  | "providerDisconnected"
  | "runnerUnavailable"
  | "configurationBlocked"
  | "failed"
  | "removing" {
  switch (lifecycle.availability) {
    case "ready":
      return "ready";
    case "stopped":
      return "stopped";
    case "transitioning":
      switch (lifecycle.convergence) {
        case "stopping":
          return "stopping";
        case "resetting":
          return "resetting";
        case "recovering":
          return "recovering";
        default:
          return "starting";
      }
    case "provider_disconnected":
      return "providerDisconnected";
    case "runner_unavailable":
      return "runnerUnavailable";
    case "configuration_blocked":
      return "configurationBlocked";
    case "failed":
      return "failed";
    case "removing":
      return "removing";
  }
}

export function RuntimeLifecycleStatus({
  lifecycle,
  compact = false,
}: RuntimeLifecycleStatusProps): React.ReactElement {
  const t = useTranslations("runtimeLifecycle");
  const reason = (() => {
    switch (lifecycle.reason_code) {
      case null:
        return null;
      case "runtime_removal_in_progress":
        return t("reasons.runtimeRemovalInProgress");
      case "runtime_failed":
        return t("reasons.runtimeFailed");
      case "provider_failed":
        return t("reasons.providerFailed");
      case "runtime_recreation_required":
        return t("reasons.runtimeRecreationRequired");
      case "provider_disabled":
        return t("reasons.providerDisabled");
      case "provider_workspace_unavailable":
        return t("reasons.providerWorkspaceUnavailable");
      case "provider_disconnected":
        return t("reasons.providerDisconnected");
      case "provider_capability_unavailable":
        return t("reasons.providerCapabilityUnavailable");
      case "provider_capability_invalid":
        return t("reasons.providerCapabilityInvalid");
      case "profile_document_invalid":
        return t("reasons.profileDocumentInvalid");
      case "profile_incompatible":
        return t("reasons.profileIncompatible");
      case "runtime_configuration_blocked":
        return t("reasons.runtimeConfigurationBlocked");
      case "runtime_profile_required":
        return t("reasons.runtimeProfileRequired");
      case "runtime_resetting":
        return t("reasons.runtimeResetting");
      case "runtime_recovering":
        return t("reasons.runtimeRecovering");
      case "runtime_starting":
        return t("reasons.runtimeStarting");
      case "runtime_stopping":
        return t("reasons.runtimeStopping");
      case "runner_unknown":
        return t("reasons.runnerUnknown");
      case "runner_disconnected":
        return t("reasons.runnerDisconnected");
      case "runner_starting":
        return t("reasons.runnerStarting");
      case "runner_degraded":
        return t("reasons.runnerDegraded");
      case "runner_failed":
        return t("reasons.runnerFailed");
      default:
        return t("reasons.unknown");
    }
  })();
  const facts: (readonly [string, string])[] = [
    [
      t("fields.executionEnvironment"),
      t(`executionEnvironment.${lifecycle.provider.resource}`),
    ],
    [
      t("fields.runtimeConnection"),
      t(`runtimeConnection.${lifecycle.runner.state}`),
    ],
    [
      t("fields.hostControls"),
      t(`hostControls.${lifecycle.provider.connection}`),
    ],
  ];

  return (
    <Paper withBorder radius="lg" p={compact ? "md" : "lg"}>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <Stack gap={2}>
            <Text fw={700}>{t("title")}</Text>
            {!compact ? (
              <Text c="dimmed" size="sm">
                {t("description")}
              </Text>
            ) : null}
          </Stack>
          <Badge
            color={availabilityColor(lifecycle.availability)}
            variant="light"
          >
            {t(`status.${statusKey(lifecycle)}`)}
          </Badge>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          {facts.map(([label, value]) => (
            <Stack key={label} gap={2}>
              <Text c="dimmed" size="xs">
                {label}
              </Text>
              <Text fw={600} size="sm">
                {value}
              </Text>
            </Stack>
          ))}
        </SimpleGrid>
        {reason ? (
          <Alert color={availabilityColor(lifecycle.availability)}>
            {reason}
          </Alert>
        ) : null}
      </Stack>
    </Paper>
  );
}
