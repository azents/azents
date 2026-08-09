"use client";

import {
  Accordion,
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type { RuntimeConfigurationState } from "../types";
import type {
  AgentRuntimeConfigurationStatusResponse,
  RuntimeConfigurationRevisionResponse,
  RuntimeContainmentStatus as RuntimeContainmentStatusData,
} from "@azents/public-client";

interface RuntimeConfigurationStatusProps {
  state: RuntimeConfigurationState;
}

type ConfigurationReason =
  | "sourceMismatch"
  | "profileDisabled"
  | "providerUnavailable"
  | "capabilityUnavailable"
  | "profileInvalid"
  | "unknown";

function configurationReason(reasonCode: string | null): ConfigurationReason {
  switch (reasonCode) {
    case "workspace_profile_provider_mismatch":
    case "infrastructure_profile_provider_mismatch":
    case "workspace_profile_infrastructure_mismatch":
      return "sourceMismatch";
    case "workspace_profile_disabled":
    case "infrastructure_profile_disabled":
      return "profileDisabled";
    case "provider_scope_unsupported":
    case "provider_not_active":
    case "provider_disabled":
    case "provider_workspace_unavailable":
    case "provider_disconnected":
      return "providerUnavailable";
    case "provider_capability_unavailable":
    case "provider_capability_invalid":
    case "profile_incompatible":
      return "capabilityUnavailable";
    case "profile_document_invalid":
      return "profileInvalid";
    default:
      return "unknown";
  }
}

function revisionEvidence(
  revision: RuntimeConfigurationRevisionResponse,
): Array<{
  label:
    | "configurationEvidence.revision"
    | "configurationEvidence.profile"
    | "configurationEvidence.infrastructure"
    | "configurationEvidence.generation"
    | "configurationEvidence.digest";
  value: string;
}> {
  return [
    { label: "configurationEvidence.revision", value: revision.id },
    {
      label: "configurationEvidence.profile",
      value: `${revision.workspace_runtime_profile_id} · v${revision.workspace_runtime_profile_version}`,
    },
    {
      label: "configurationEvidence.infrastructure",
      value: `${revision.infrastructure_profile_id} · v${revision.infrastructure_profile_version}`,
    },
    {
      label: "configurationEvidence.generation",
      value: revision.target_desired_generation.toString(),
    },
    { label: "configurationEvidence.digest", value: revision.digest },
  ];
}

function RevisionPanel({
  title,
  revision,
}: {
  title: string;
  revision: RuntimeConfigurationRevisionResponse;
}): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          {title}
        </Text>
        {revisionEvidence(revision).map((item) => (
          <Stack key={item.label} gap={0}>
            <Text size="xs" fw={500}>
              {t(item.label)}
            </Text>
            <Text
              size="xs"
              ff="monospace"
              style={{
                overflowWrap: "anywhere",
                wordBreak: "break-word",
              }}
            >
              {item.value}
            </Text>
          </Stack>
        ))}
        {revision.reason_code !== null && (
          <Alert color="red" p="xs">
            <Stack gap="xs">
              <Text size="xs">
                {t(
                  `configurationReasons.${configurationReason(
                    revision.reason_code,
                  )}`,
                )}
              </Text>
              <Text
                size="xs"
                ff="monospace"
                style={{ overflowWrap: "anywhere" }}
              >
                {revision.reason_code}
              </Text>
              {revision.missing_capabilities.length > 0 && (
                <Text
                  size="xs"
                  ff="monospace"
                  style={{ overflowWrap: "anywhere" }}
                >
                  {t("configurationMissingCapabilities", {
                    capabilities: revision.missing_capabilities.join(", "),
                  })}
                </Text>
              )}
            </Stack>
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}

type ContainmentAvailabilityDescription =
  | "containment.availability.availableDescription"
  | "containment.availability.recreationDescription"
  | "containment.availability.blockedDescription"
  | "containment.availability.unavailableDescription";

function ContainmentStatus({
  containment,
  configurationStatus,
}: {
  containment: RuntimeContainmentStatusData;
  configurationStatus: AgentRuntimeConfigurationStatusResponse["status"];
}): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const availabilityDescription: ContainmentAvailabilityDescription =
    containment.runtime_available
      ? "containment.availability.availableDescription"
      : containment.recreation_required
        ? "containment.availability.recreationDescription"
        : configurationStatus === "configuration_blocked"
          ? "containment.availability.blockedDescription"
          : "containment.availability.unavailableDescription";

  const statuses = [
    {
      label: t("containment.enabled.label"),
      value: containment.enabled
        ? t("containment.enabled.enabled")
        : t("containment.enabled.disabled"),
      color: containment.enabled ? "green" : "gray",
    },
    {
      label: t("containment.applied.label"),
      value: !containment.enabled
        ? t("containment.applied.notEnabled")
        : containment.applied
          ? t("containment.applied.applied")
          : t("containment.applied.pending"),
      color: !containment.enabled
        ? "gray"
        : containment.applied
          ? "green"
          : "yellow",
    },
    {
      label: t("containment.recreation.label"),
      value: containment.recreation_required
        ? t("containment.recreation.required")
        : t("containment.recreation.notRequired"),
      color: containment.recreation_required ? "yellow" : "gray",
    },
    {
      label: t("containment.availability.label"),
      value: containment.runtime_available
        ? t("containment.availability.available")
        : t("containment.availability.unavailable"),
      color: containment.runtime_available ? "green" : "red",
    },
  ];

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        {t("containment.title")}
      </Text>
      <Paper withBorder p="sm" radius="md">
        <Stack gap="xs">
          {statuses.map((status) => (
            <Group
              key={status.label}
              justify="space-between"
              align="center"
              gap="sm"
              wrap="nowrap"
            >
              <Text size="xs">{status.label}</Text>
              <Badge color={status.color} variant="light" size="sm">
                {status.value}
              </Badge>
            </Group>
          ))}
        </Stack>
      </Paper>
      <Text size="xs" c="dimmed">
        {t(availabilityDescription)}
      </Text>
    </Stack>
  );
}

export function RuntimeConfigurationStatus({
  state,
}: RuntimeConfigurationStatusProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  if (state.type === "LOADING") {
    return (
      <Paper withBorder p="md" radius="md">
        <Group gap="sm">
          <Loader size="xs" />
          <Text size="sm">{t("configurationLoading")}</Text>
        </Group>
      </Paper>
    );
  }

  if (state.type === "ERROR") {
    return <Alert color="red">{state.message}</Alert>;
  }

  const { configuration } = state;
  const hasTechnicalDetails =
    configuration.desired !== null || configuration.applied !== null;

  return (
    <Paper withBorder p={{ base: "sm", sm: "md" }} radius="md">
      <Stack gap="md">
        <Stack gap="xs">
          <Group justify="space-between" align="center" gap="sm">
            <Text size="sm" fw={700}>
              {t("configurationTitle")}
            </Text>
            <Badge variant="default">
              {t(`configurationStatus.${configuration.status}.label`)}
            </Badge>
          </Group>
          <Text size="sm">
            {t(`configurationStatus.${configuration.status}.description`)}
          </Text>
        </Stack>

        <ContainmentStatus
          containment={configuration.containment}
          configurationStatus={configuration.status}
        />

        {hasTechnicalDetails && (
          <Accordion variant="contained" radius="md">
            <Accordion.Item value="technical-details">
              <Accordion.Control>
                <Text size="sm" fw={600}>
                  {t("configurationTechnicalDetails")}
                </Text>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="sm">
                  {configuration.status === "applied" &&
                  configuration.applied !== null ? (
                    <RevisionPanel
                      title={t("configurationCurrent")}
                      revision={configuration.applied}
                    />
                  ) : (
                    <>
                      {configuration.desired !== null && (
                        <RevisionPanel
                          title={t("configurationDesired")}
                          revision={configuration.desired}
                        />
                      )}
                      {configuration.applied !== null && (
                        <RevisionPanel
                          title={t("configurationApplied")}
                          revision={configuration.applied}
                        />
                      )}
                    </>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        )}
      </Stack>
    </Paper>
  );
}
