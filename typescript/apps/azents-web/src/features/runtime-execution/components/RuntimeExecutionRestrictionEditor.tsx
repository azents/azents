"use client";

import {
  Checkbox,
  Grid,
  NumberInput,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { ByteSizeInput } from "./ByteSizeInput";
import type {
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

function lines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

const EMPTY_RESOURCES: RuntimeExecutionResourceRestriction = {
  cpu_request_millicores: null,
  cpu_limit_millicores: null,
  memory_request_bytes: null,
  memory_limit_bytes: null,
  pids: null,
  container_count: null,
  ephemeral_storage_bytes: null,
  persistent_storage_bytes: null,
};

export function RuntimeExecutionRestrictionEditor({
  restriction,
  readOnly = false,
  onChange,
}: RuntimeExecutionRestrictionEditorProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.restrictions");
  const resources = restriction.resources ?? EMPTY_RESOURCES;
  const storage = restriction.engine_storage ?? {
    mode: null,
    capacity_bytes: null,
  };
  const network = restriction.network_egress ?? {
    mode: null,
    allowed_destinations: null,
    denied_destinations: [],
  };
  const updateResources = (
    values: Partial<RuntimeExecutionResourceRestriction>,
  ): void => {
    onChange({
      ...restriction,
      resources: { ...resources, ...values },
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
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Checkbox
              label={t("disableImageBuild")}
              checked={restriction.image_build !== null}
              disabled={readOnly}
              onChange={(event) =>
                onChange({
                  ...restriction,
                  image_build: event.currentTarget.checked
                    ? { enabled: false }
                    : null,
                })
              }
            />
            <Checkbox
              label={t("disableContainerRun")}
              checked={restriction.container_run !== null}
              disabled={readOnly}
              onChange={(event) =>
                onChange({
                  ...restriction,
                  container_run: event.currentTarget.checked
                    ? { enabled: false }
                    : null,
                })
              }
            />
            <Checkbox
              label={t("disableCompose")}
              checked={restriction.compose !== null}
              disabled={readOnly}
              onChange={(event) =>
                onChange({
                  ...restriction,
                  compose: event.currentTarget.checked
                    ? { enabled: false }
                    : null,
                })
              }
            />
          </SimpleGrid>
          <Stack gap={2}>
            <Text size="sm" fw={500}>
              {t("nestedContainerLimits")}
            </Text>
            <Text size="xs" c="dimmed">
              {t("optionalRestrictionDescription")}
            </Text>
          </Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <NumberInput
              label={t("aggregatePidLimit")}
              description={t("inheritWhenEmpty")}
              value={resources.pids ?? ""}
              min={1}
              placeholder={t("pidPlaceholder")}
              disabled={readOnly}
              onChange={(value) =>
                updateResources({ pids: optionalNumber(value) })
              }
            />
            <NumberInput
              label={t("containerCountLimit")}
              description={t("inheritWhenEmpty")}
              value={resources.container_count ?? ""}
              min={1}
              placeholder={t("containerPlaceholder")}
              disabled={readOnly}
              onChange={(value) =>
                updateResources({ container_count: optionalNumber(value) })
              }
            />
          </SimpleGrid>
          <Select
            label={t("dockerStoragePolicy")}
            description={t("dockerStorageDescription")}
            data={[
              { value: "inherit", label: t("inheritProfile") },
              { value: "none", label: t("storageNone") },
              { value: "ephemeral", label: t("storageEphemeral") },
            ]}
            value={storage.mode ?? "inherit"}
            allowDeselect={false}
            disabled={readOnly}
            onChange={(value) => {
              if (value === null) {
                return;
              }
              onChange({
                ...restriction,
                engine_storage: {
                  ...storage,
                  mode: value === "inherit" ? null : value,
                },
              });
            }}
          />
          <ByteSizeInput
            label={t("temporaryDockerStorage")}
            description={t("inheritWhenEmpty")}
            unitLabel={t("unit")}
            value={storage.capacity_bytes}
            placeholder={t("storagePlaceholder")}
            disabled={readOnly || storage.mode === "none"}
            onChange={(value) =>
              onChange({
                ...restriction,
                engine_storage: { ...storage, capacity_bytes: value },
              })
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

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>{t("networkTitle")}</Text>
            <Text size="sm" c="dimmed">
              {t("networkDescription")}
            </Text>
          </Stack>
          <Select
            label={t("accessPolicy")}
            data={[
              { value: "inherit", label: t("inheritProfile") },
              { value: "none", label: t("networkNone") },
              { value: "restricted", label: t("networkRestricted") },
              { value: "direct", label: t("networkDirect") },
            ]}
            value={network.mode ?? "inherit"}
            allowDeselect={false}
            disabled={readOnly}
            onChange={(value) => {
              if (value === null) {
                return;
              }
              onChange({
                ...restriction,
                network_egress: {
                  ...network,
                  mode: value === "inherit" ? null : value,
                },
              });
            }}
          />
          {network.mode === "restricted" && (
            <Textarea
              label={t("allowedIpRanges")}
              description={t("cidrDescription")}
              placeholder={t("allowedCidrPlaceholder")}
              value={(network.allowed_destinations ?? []).join("\n")}
              disabled={readOnly}
              autosize
              minRows={3}
              onChange={(event) =>
                onChange({
                  ...restriction,
                  network_egress: {
                    ...network,
                    allowed_destinations: lines(event.currentTarget.value),
                  },
                })
              }
            />
          )}
          {network.mode !== "none" && (
            <Textarea
              label={t("blockedIpRanges")}
              description={t("blockedCidrDescription")}
              placeholder={t("blockedCidrPlaceholder")}
              value={network.denied_destinations.join("\n")}
              disabled={readOnly}
              autosize
              minRows={3}
              onChange={(event) =>
                onChange({
                  ...restriction,
                  network_egress: {
                    ...network,
                    denied_destinations: lines(event.currentTarget.value),
                  },
                })
              }
            />
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}
