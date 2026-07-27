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
import {
  isSupportedRuntimeExecutionNetworkMode,
  isSupportedRuntimeExecutionStorageMode,
} from "../runtimeExecutionPresentation";
import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
} from "@azents/admin-client";

interface RuntimeExecutionPolicyEditorProps {
  policy: RuntimeExecutionPolicyDocument;
  capabilities: RuntimeExecutionManagementCapabilitiesResponse;
  readOnly?: boolean;
  onChange: (policy: RuntimeExecutionPolicyDocument) => void;
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

export function RuntimeExecutionPolicyEditor({
  policy,
  capabilities,
  readOnly = false,
  onChange,
}: RuntimeExecutionPolicyEditorProps): React.ReactElement {
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Text fw={600}>Container capabilities</Text>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Checkbox
              label="Build container images"
              checked={policy.image_build.enabled}
              disabled={
                readOnly ||
                (!capabilities.image_build && !policy.image_build.enabled)
              }
              onChange={(event) => {
                const enabled = event.currentTarget.checked;
                if (enabled && !capabilities.image_build) {
                  return;
                }
                onChange({
                  ...policy,
                  image_build: {
                    ...policy.image_build,
                    enabled,
                  },
                });
              }}
            />
            <Checkbox
              label="Run nested containers"
              checked={policy.container_run.enabled}
              disabled={
                readOnly ||
                (!capabilities.container_run && !policy.container_run.enabled)
              }
              onChange={(event) => {
                const enabled = event.currentTarget.checked;
                if (enabled && !capabilities.container_run) {
                  return;
                }
                onChange({
                  ...policy,
                  container_run: {
                    ...policy.container_run,
                    enabled,
                  },
                });
              }}
            />
            <Checkbox
              label="Use Compose"
              checked={policy.compose.enabled}
              disabled={
                readOnly || (!capabilities.compose && !policy.compose.enabled)
              }
              onChange={(event) => {
                const enabled = event.currentTarget.checked;
                if (enabled && !capabilities.compose) {
                  return;
                }
                onChange({
                  ...policy,
                  compose: {
                    ...policy.compose,
                    enabled,
                  },
                });
              }}
            />
          </SimpleGrid>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Text fw={600}>Resource ceilings</Text>
          <Grid>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label="CPU millicores"
                value={policy.resources.cpu_millicores ?? ""}
                min={0}
                disabled={readOnly}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      cpu_millicores: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label="Memory bytes"
                value={policy.resources.memory_bytes ?? ""}
                min={0}
                disabled={readOnly}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      memory_bytes: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label="Process limit"
                value={policy.resources.pids ?? ""}
                min={0}
                disabled={readOnly}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      pids: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label="Container count"
                value={policy.resources.container_count ?? ""}
                min={0}
                disabled={readOnly}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      container_count: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6, lg: 4 }}>
              <NumberInput
                label="Ephemeral storage bytes"
                value={policy.resources.ephemeral_storage_bytes ?? ""}
                min={0}
                disabled={readOnly}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
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
          <Text fw={600}>Engine storage</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label="Mode"
              data={[
                {
                  value: "none",
                  label: "None",
                  disabled: !capabilities.storage_modes.includes("none"),
                },
                {
                  value: "ephemeral",
                  label: "Ephemeral",
                  disabled: !capabilities.storage_modes.includes("ephemeral"),
                },
              ]}
              value={policy.engine_storage.mode}
              disabled={readOnly}
              allowDeselect={false}
              onChange={(value) => {
                if (
                  value === null ||
                  !isSupportedRuntimeExecutionStorageMode(value, capabilities)
                ) {
                  return;
                }
                onChange({
                  ...policy,
                  engine_storage: {
                    ...policy.engine_storage,
                    mode: value,
                  },
                });
              }}
            />
            <NumberInput
              label="Capacity bytes"
              value={policy.engine_storage.capacity_bytes ?? ""}
              min={0}
              disabled={readOnly}
              onChange={(value) =>
                onChange({
                  ...policy,
                  engine_storage: {
                    ...policy.engine_storage,
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
          <Text fw={600}>Network egress</Text>
          <Select
            label="Mode"
            data={[
              {
                value: "none",
                label: "None",
                disabled: !capabilities.network_modes.includes("none"),
              },
              {
                value: "restricted",
                label: "Restricted",
                disabled: !capabilities.network_modes.includes("restricted"),
              },
              {
                value: "direct",
                label: "Direct",
                disabled: !capabilities.network_modes.includes("direct"),
              },
            ]}
            value={policy.network_egress.mode}
            disabled={readOnly}
            allowDeselect={false}
            onChange={(value) => {
              if (
                value === null ||
                !isSupportedRuntimeExecutionNetworkMode(value, capabilities)
              ) {
                return;
              }
              onChange({
                ...policy,
                network_egress: {
                  ...policy.network_egress,
                  mode: value,
                },
              });
            }}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Textarea
              label="Allowed destinations"
              description="One destination per line."
              value={policy.network_egress.allowed_destinations.join("\n")}
              disabled={readOnly}
              autosize
              minRows={3}
              onChange={(event) =>
                onChange({
                  ...policy,
                  network_egress: {
                    ...policy.network_egress,
                    allowed_destinations: lines(event.currentTarget.value),
                  },
                })
              }
            />
            <Textarea
              label="Denied destinations"
              description="One destination per line."
              value={policy.network_egress.denied_destinations.join("\n")}
              disabled={readOnly}
              autosize
              minRows={3}
              onChange={(event) =>
                onChange({
                  ...policy,
                  network_egress: {
                    ...policy.network_egress,
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
