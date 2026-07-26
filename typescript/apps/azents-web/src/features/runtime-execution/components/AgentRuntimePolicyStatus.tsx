"use client";

import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { canApplyRuntimeExecution } from "../runtimeExecutionPresentation";
import type { AgentRuntimeStatusState } from "../types";
import type {
  RuntimeExecutionConfiguredSummaryResponse,
  RuntimeExecutionPolicyStatus,
  RuntimeExecutionSnapshotSummaryResponse,
} from "@azents/public-client";

interface AgentRuntimePolicyStatusProps {
  state: AgentRuntimeStatusState;
  applying: boolean;
  onApply: () => void;
}

function statusColor(status: RuntimeExecutionPolicyStatus): string {
  switch (status) {
    case "configured":
      return "blue";
    case "pending":
      return "yellow";
    case "applied":
      return "green";
    case "unavailable":
      return "orange";
    case "divergent":
      return "red";
  }
}

function Summary({
  title,
  summary,
}: {
  title: string;
  summary:
    | RuntimeExecutionConfiguredSummaryResponse
    | RuntimeExecutionSnapshotSummaryResponse
    | null;
}): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.agentPage");
  if (summary === null) {
    return (
      <Paper withBorder p="md" radius="md">
        <Stack gap={3}>
          <Text size="sm" fw={600}>
            {title}
          </Text>
          <Text size="sm" c="dimmed">
            {t("none")}
          </Text>
        </Stack>
      </Paper>
    );
  }
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={600}>
            {title}
          </Text>
          {"desired_generation" in summary && (
            <Badge variant="light">
              {t("generation", {
                generation: summary.desired_generation,
              })}
            </Badge>
          )}
        </Group>
        <Text size="sm">
          {t("profileValue", { profile: summary.profile_id })}
        </Text>
        <Code>{summary.digest.slice(0, 16)}</Code>
        <Text size="xs" c="dimmed">
          {t("storage")}: {summary.storage_mode}
          {summary.storage_capacity_bytes === null
            ? ""
            : ` · ${summary.storage_capacity_bytes}`}
        </Text>
        <Text size="xs" c="dimmed">
          {t("network")}: {summary.network_mode}
        </Text>
        <Group gap="xs">
          {summary.capabilities.map((capability) => (
            <Badge
              key={capability.module_id}
              color={capability.enabled ? "blue" : "gray"}
              variant="light"
              size="sm"
            >
              {capability.module_id}:{" "}
              {capability.enabled ? t("enabled") : t("disabled")}
            </Badge>
          ))}
        </Group>
      </Stack>
    </Paper>
  );
}

export function AgentRuntimePolicyStatus({
  state,
  applying,
  onApply,
}: AgentRuntimePolicyStatusProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.agentPage");
  if (state.type === "LOADING") {
    return (
      <Paper withBorder p="md" radius="md">
        <Group>
          <Loader size="sm" />
          <Text>{t("statusLoading")}</Text>
        </Group>
      </Paper>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="yellow" title={t("statusError")}>
        {state.message}
      </Alert>
    );
  }
  const { status } = state;
  const statusLabel = {
    configured: t("status.configured"),
    pending: t("status.pending"),
    applied: t("status.applied"),
    unavailable: t("status.unavailable"),
    divergent: t("status.divergent"),
  }[status.status];
  const statusHelp = {
    configured: t("statusHelp.configured"),
    pending: t("statusHelp.pending"),
    applied: t("statusHelp.applied"),
    unavailable: t("statusHelp.unavailable"),
    divergent: t("statusHelp.divergent"),
  }[status.status];
  const actionLabel = {
    none: t("actions.none"),
    apply: t("actions.apply"),
    wait: t("actions.wait"),
    administrator_action: t("actions.administrator_action"),
  }[status.required_action];

  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Group gap="xs">
              <Text fw={600}>{t("statusTitle")}</Text>
              <Badge color={statusColor(status.status)} variant="light">
                {statusLabel}
              </Badge>
            </Group>
            <Text size="sm" c="dimmed">
              {statusHelp}
            </Text>
            <Text size="sm">{actionLabel}</Text>
          </Stack>
          {canApplyRuntimeExecution(status.required_action) && (
            <Button loading={applying} onClick={onApply}>
              {applying ? t("applying") : t("apply")}
            </Button>
          )}
        </Group>
        {(status.reason_codes.length > 0 ||
          Object.keys(status.governing_layers).length > 0) && (
          <SimpleGrid cols={{ base: 1, sm: 2 }} mt="md">
            <Stack gap={3}>
              <Text size="xs" fw={600} c="dimmed">
                {t("reasonCodes")}
              </Text>
              <Text size="sm">
                {status.reason_codes.join(", ") || t("none")}
              </Text>
            </Stack>
            <Stack gap={3}>
              <Text size="xs" fw={600} c="dimmed">
                {t("governingLayers")}
              </Text>
              <Text size="sm">
                {Object.entries(status.governing_layers)
                  .map(([path, layer]) => `${path}: ${layer}`)
                  .join(", ") || t("none")}
              </Text>
            </Stack>
          </SimpleGrid>
        )}
      </Paper>
      <Text fw={600}>{t("comparisonTitle")}</Text>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Summary title={t("configured")} summary={status.configured} />
        <Summary title={t("target")} summary={status.target} />
        <Summary title={t("applied")} summary={status.applied} />
      </SimpleGrid>
    </Stack>
  );
}
