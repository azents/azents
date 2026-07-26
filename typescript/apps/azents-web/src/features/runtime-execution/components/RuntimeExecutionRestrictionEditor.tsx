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
import type { RuntimeExecutionPolicyRestriction } from "@azents/public-client";

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

export function RuntimeExecutionRestrictionEditor({
  restriction,
  readOnly = false,
  onChange,
}: RuntimeExecutionRestrictionEditorProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeExecution.restrictions");
  const resources = restriction.resources ?? {
    cpu_millicores: null,
    memory_bytes: null,
    pids: null,
    container_count: null,
    ephemeral_storage_bytes: null,
  };
  const storage = restriction.engine_storage ?? {
    mode: null,
    capacity_bytes: null,
  };
  const network = restriction.network_egress ?? {
    mode: null,
    allowed_destinations: null,
    denied_destinations: [],
  };

  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Text fw={600}>{t("capabilitiesTitle")}</Text>
          <Text size="sm" c="dimmed">
            {t("capabilitiesDescription")}
          </Text>
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
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Checkbox
            label={t("resourceTitle")}
            checked={restriction.resources !== null}
            disabled={readOnly}
            onChange={(event) =>
              onChange({
                ...restriction,
                resources: event.currentTarget.checked ? resources : null,
              })
            }
          />
          <Grid>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label={t("cpuMillicores")}
                value={resources.cpu_millicores ?? ""}
                min={0}
                disabled={readOnly || restriction.resources === null}
                onChange={(value) =>
                  onChange({
                    ...restriction,
                    resources: {
                      ...resources,
                      cpu_millicores: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label={t("memoryBytes")}
                value={resources.memory_bytes ?? ""}
                min={0}
                disabled={readOnly || restriction.resources === null}
                onChange={(value) =>
                  onChange({
                    ...restriction,
                    resources: {
                      ...resources,
                      memory_bytes: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label={t("pids")}
                value={resources.pids ?? ""}
                min={0}
                disabled={readOnly || restriction.resources === null}
                onChange={(value) =>
                  onChange({
                    ...restriction,
                    resources: { ...resources, pids: optionalNumber(value) },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label={t("containerCount")}
                value={resources.container_count ?? ""}
                min={0}
                disabled={readOnly || restriction.resources === null}
                onChange={(value) =>
                  onChange({
                    ...restriction,
                    resources: {
                      ...resources,
                      container_count: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label={t("ephemeralStorageBytes")}
                value={resources.ephemeral_storage_bytes ?? ""}
                min={0}
                disabled={readOnly || restriction.resources === null}
                onChange={(value) =>
                  onChange({
                    ...restriction,
                    resources: {
                      ...resources,
                      ephemeral_storage_bytes: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
          </Grid>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Checkbox
            label={t("storageTitle")}
            checked={restriction.engine_storage !== null}
            disabled={readOnly}
            onChange={(event) =>
              onChange({
                ...restriction,
                engine_storage: event.currentTarget.checked ? storage : null,
              })
            }
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label={t("mode")}
              data={[
                { value: "inherit", label: t("inherit") },
                { value: "none", label: t("storageNone") },
                { value: "ephemeral", label: t("storageEphemeral") },
              ]}
              value={storage.mode ?? "inherit"}
              allowDeselect={false}
              disabled={readOnly || restriction.engine_storage === null}
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
            <NumberInput
              label={t("capacityBytes")}
              value={storage.capacity_bytes ?? ""}
              min={0}
              disabled={readOnly || restriction.engine_storage === null}
              onChange={(value) =>
                onChange({
                  ...restriction,
                  engine_storage: {
                    ...storage,
                    capacity_bytes: optionalNumber(value),
                  },
                })
              }
            />
          </SimpleGrid>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Checkbox
            label={t("networkTitle")}
            checked={restriction.network_egress !== null}
            disabled={readOnly}
            onChange={(event) =>
              onChange({
                ...restriction,
                network_egress: event.currentTarget.checked ? network : null,
              })
            }
          />
          <Select
            label={t("mode")}
            data={[
              { value: "inherit", label: t("inherit") },
              { value: "none", label: t("networkNone") },
              { value: "proxy_required", label: t("networkProxy") },
              { value: "restricted", label: t("networkRestricted") },
              { value: "direct", label: t("networkDirect") },
            ]}
            value={network.mode ?? "inherit"}
            allowDeselect={false}
            disabled={readOnly || restriction.network_egress === null}
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
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Textarea
              label={t("allowedDestinations")}
              description={t("onePerLine")}
              value={(network.allowed_destinations ?? []).join("\n")}
              disabled={readOnly || restriction.network_egress === null}
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
            <Textarea
              label={t("deniedDestinations")}
              description={t("onePerLine")}
              value={network.denied_destinations.join("\n")}
              disabled={readOnly || restriction.network_egress === null}
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
          </SimpleGrid>
        </Stack>
      </Paper>
    </Stack>
  );
}
