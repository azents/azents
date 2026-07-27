"use client";

import {
  Checkbox,
  Grid,
  NumberInput,
  Paper,
  Select,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { ByteSizeInput } from "./ByteSizeInput";
import type {
  RuntimeExecutionDockerRestriction,
  RuntimeExecutionPolicyRestriction,
  RuntimeExecutionResourceRestriction,
} from "@azents/public-client";

interface RuntimeExecutionRestrictionEditorProps {
  restriction: RuntimeExecutionPolicyRestriction;
  readOnly?: boolean;
  onChange: (restriction: RuntimeExecutionPolicyRestriction) => void;
}

function optionalNumber(value: string | number): number | null {
  return typeof value === "number" ? value : null;
}

const EMPTY_RESOURCES: RuntimeExecutionResourceRestriction = {
  cpu_request_millicores: null,
  cpu_limit_millicores: null,
  memory_request_bytes: null,
  memory_limit_bytes: null,
  ephemeral_storage_bytes: null,
  persistent_storage_bytes: null,
};

const EMPTY_DOCKER: RuntimeExecutionDockerRestriction = {
  enabled: null,
  storage_mode: null,
  storage_capacity_bytes: null,
};

export function RuntimeExecutionRestrictionEditor({
  restriction,
  readOnly = false,
  onChange,
}: RuntimeExecutionRestrictionEditorProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.restrictions");
  const resources = restriction.resources ?? EMPTY_RESOURCES;
  const docker = restriction.docker ?? EMPTY_DOCKER;
  const updateResources = (
    values: Partial<RuntimeExecutionResourceRestriction>,
  ): void => {
    onChange({
      ...restriction,
      resources: { ...resources, ...values },
    });
  };
  const updateDocker = (
    values: Partial<RuntimeExecutionDockerRestriction>,
  ): void => {
    onChange({
      ...restriction,
      docker: { ...docker, ...values },
    });
  };

  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>{t("dockerTitle")}</Text>
            <Text size="sm" c="dimmed">
              {t("dockerDescription")}
            </Text>
          </Stack>
          <Checkbox
            label={t("disableDocker")}
            checked={docker.enabled === false}
            disabled={readOnly}
            onChange={(event) =>
              updateDocker({
                enabled: event.currentTarget.checked ? false : null,
                storage_mode: null,
                storage_capacity_bytes: null,
              })
            }
          />
          <Select
            label={t("dockerStoragePolicy")}
            description={t("dockerStorageDescription")}
            data={[
              { value: "inherit", label: t("inheritProfile") },
              { value: "ephemeral", label: t("storageEphemeral") },
            ]}
            value={docker.storage_mode ?? "inherit"}
            allowDeselect={false}
            disabled={readOnly || docker.enabled === false}
            onChange={(value) => {
              if (value !== null) {
                updateDocker({
                  storage_mode: value === "inherit" ? null : value,
                });
              }
            }}
          />
          <ByteSizeInput
            label={t("temporaryDockerStorage")}
            description={t("inheritWhenEmpty")}
            unitLabel={t("unit")}
            value={docker.storage_capacity_bytes}
            placeholder={t("storagePlaceholder")}
            disabled={readOnly || docker.enabled === false}
            onChange={(value) =>
              updateDocker({ storage_capacity_bytes: value })
            }
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>{t("kubernetesResourcesTitle")}</Text>
            <Text size="sm" c="dimmed">
              {t("kubernetesResourcesDescription")}
            </Text>
          </Stack>
          <Grid>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <NumberInput
                label={t("cpuRequestMillicores")}
                description={t("inheritWhenEmpty")}
                value={resources.cpu_request_millicores ?? ""}
                min={1}
                placeholder={t("cpuRequestPlaceholder")}
                disabled={readOnly}
                onChange={(value) =>
                  updateResources({
                    cpu_request_millicores: optionalNumber(value),
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <NumberInput
                label={t("cpuLimitMillicores")}
                description={t("inheritWhenEmpty")}
                value={resources.cpu_limit_millicores ?? ""}
                min={1}
                placeholder={t("cpuLimitPlaceholder")}
                disabled={readOnly}
                onChange={(value) =>
                  updateResources({
                    cpu_limit_millicores: optionalNumber(value),
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label={t("memoryRequest")}
                description={t("inheritWhenEmpty")}
                unitLabel={t("unit")}
                value={resources.memory_request_bytes}
                placeholder={t("memoryRequestPlaceholder")}
                disabled={readOnly}
                onChange={(value) =>
                  updateResources({ memory_request_bytes: value })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label={t("memoryLimit")}
                description={t("inheritWhenEmpty")}
                unitLabel={t("unit")}
                value={resources.memory_limit_bytes}
                placeholder={t("memoryLimitPlaceholder")}
                disabled={readOnly}
                onChange={(value) =>
                  updateResources({ memory_limit_bytes: value })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label={t("ephemeralStorage")}
                description={t("ephemeralStorageDescription")}
                unitLabel={t("unit")}
                value={resources.ephemeral_storage_bytes}
                placeholder={t("ephemeralPlaceholder")}
                disabled={readOnly}
                onChange={(value) =>
                  updateResources({ ephemeral_storage_bytes: value })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label={t("persistentStorage")}
                description={t("persistentStorageDescription")}
                unitLabel={t("unit")}
                value={resources.persistent_storage_bytes}
                placeholder={t("persistentPlaceholder")}
                disabled={readOnly}
                onChange={(value) =>
                  updateResources({ persistent_storage_bytes: value })
                }
              />
            </Grid.Col>
          </Grid>
        </Stack>
      </Paper>
    </Stack>
  );
}
