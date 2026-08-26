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
  RuntimeConfigurationNetworkResponse,
  RuntimeConfigurationStateResponse,
} from "@azents/public-client";

interface RuntimeConfigurationStatusProps {
  state: RuntimeConfigurationState;
}

type ConfigurationNetworkDomainMode = "unrestricted" | "allowlist";

function configurationNetworkDomainMode(
  domainMode: string,
): ConfigurationNetworkDomainMode | null {
  switch (domainMode) {
    case "unrestricted":
    case "allowlist":
      return domainMode;
    default:
      return null;
  }
}

function NetworkSummary({
  network,
}: {
  network: RuntimeConfigurationNetworkResponse;
}): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const domainMode =
    network.domain_mode === null
      ? null
      : configurationNetworkDomainMode(network.domain_mode);

  return (
    <Stack gap={2}>
      <Text size="xs">
        {t("configurationNetworkMode", {
          mode: t(`configurationNetworkModes.${network.mode}`),
        })}
      </Text>
      <Text size="xs">
        {t("configurationNetworkProtocol", {
          protocol: t(
            `configurationNetworkProtocols.${network.protocol_summary}`,
          ),
        })}
      </Text>
      {domainMode !== null ? (
        <Text size="xs">
          {t("configurationNetworkDomains", {
            mode: t(`configurationNetworkDomainModes.${domainMode}`),
          })}
        </Text>
      ) : null}
      <Text size="xs">
        {network.https_inspection
          ? t("configurationNetworkHttpsInspected")
          : t("configurationNetworkHttpsNotInspected")}
      </Text>
    </Stack>
  );
}

function ConfiguredValues({
  title,
  configurationState,
}: {
  title: string;
  configurationState: RuntimeConfigurationStateResponse;
}): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");
  const runtimeProfile =
    configurationState.workspace_runtime_profile_id === null
      ? t("configurationValueUnavailable")
      : configurationState.workspace_runtime_profile_version === null
        ? configurationState.workspace_runtime_profile_id
        : `${configurationState.workspace_runtime_profile_id} · v${configurationState.workspace_runtime_profile_version}`;
  const executionProfile =
    configurationState.infrastructure_profile_id === null
      ? t("configurationValueUnavailable")
      : configurationState.infrastructure_profile_version === null
        ? configurationState.infrastructure_profile_id
        : `${configurationState.infrastructure_profile_id} · v${configurationState.infrastructure_profile_version}`;

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          {title}
        </Text>
        <Stack gap={0}>
          <Text c="dimmed" size="xs">
            {t("configurationProfile")}
          </Text>
          <Text size="sm">{runtimeProfile}</Text>
        </Stack>
        <Stack gap={0}>
          <Text c="dimmed" size="xs">
            {t("configurationExecutionProfile")}
          </Text>
          <Text size="sm">{executionProfile}</Text>
        </Stack>
        {configurationState.network !== null ? (
          <Stack gap={2}>
            <Text c="dimmed" size="xs">
              {t("configurationNetworkTitle")}
            </Text>
            <NetworkSummary network={configurationState.network} />
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}

export function RuntimeConfigurationStatus({
  state,
}: RuntimeConfigurationStatusProps): React.ReactElement | null {
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
  if (configuration === null) {
    return null;
  }
  const hasConfiguredValues =
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
        {hasConfiguredValues ? (
          <Accordion variant="contained" radius="md">
            <Accordion.Item value="configured-values">
              <Accordion.Control>
                <Text size="sm" fw={600}>
                  {t("configurationConfiguredValues")}
                </Text>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="sm">
                  {configuration.status === "applied" &&
                  configuration.applied !== null ? (
                    <ConfiguredValues
                      title={t("configurationApplied")}
                      configurationState={configuration.applied}
                    />
                  ) : (
                    <>
                      {configuration.desired !== null ? (
                        <ConfiguredValues
                          title={t("configurationDesired")}
                          configurationState={configuration.desired}
                        />
                      ) : null}
                      {configuration.applied !== null ? (
                        <ConfiguredValues
                          title={t("configurationApplied")}
                          configurationState={configuration.applied}
                        />
                      ) : null}
                    </>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        ) : null}
      </Stack>
    </Paper>
  );
}
