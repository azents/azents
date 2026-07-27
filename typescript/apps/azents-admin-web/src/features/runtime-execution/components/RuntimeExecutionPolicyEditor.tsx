"use client";

import { Checkbox, Grid, NumberInput, Paper, Stack, Text } from "@mantine/core";
import { updateRuntimeExecutionDocker } from "../runtimeExecutionPresentation";
import { ByteSizeInput } from "./ByteSizeInput";
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

export function RuntimeExecutionPolicyEditor({
  policy,
  capabilities,
  readOnly = false,
  onChange,
}: RuntimeExecutionPolicyEditorProps): React.ReactElement {
  const dockerEnabled = policy.docker.enabled;
  const dockerSupported =
    capabilities.docker && capabilities.storage_modes.includes("ephemeral");

  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>Docker</Text>
            <Text size="sm" c="dimmed">
              Enables the complete Docker API inside the Runtime, including
              image builds, containers, Compose, published ports, and
              Testcontainers. This initial implementation uses privileged DIND.
            </Text>
          </Stack>
          <Checkbox
            label="Enable Docker"
            description="Docker data is temporary and is deleted when the Runtime Pod is replaced."
            checked={dockerEnabled}
            disabled={readOnly || (!dockerSupported && !dockerEnabled)}
            onChange={(event) =>
              onChange(
                updateRuntimeExecutionDocker(
                  policy,
                  event.currentTarget.checked,
                ),
              )
            }
          />
          <ByteSizeInput
            label="Temporary Docker data capacity"
            description="Maximum size of the private volume used for images, containers, volumes, and build cache."
            value={policy.docker.storage_capacity_bytes}
            required={dockerEnabled}
            placeholder="e.g. 16"
            disabled={readOnly || !dockerEnabled}
            onChange={(value) =>
              onChange({
                ...policy,
                docker: {
                  ...policy.docker,
                  storage_capacity_bytes: value,
                },
              })
            }
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>Docker service Kubernetes resources</Text>
            <Text size="sm" c="dimmed">
              CPU and memory Requests and Limits apply to the privileged DIND
              sidecar. They are optional. Ephemeral storage uses the same value
              for its Kubernetes Request and Limit.
            </Text>
          </Stack>
          <Grid>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <NumberInput
                label="CPU Request (millicores)"
                value={policy.resources.cpu_request_millicores ?? ""}
                min={1}
                placeholder="e.g. 500"
                disabled={readOnly || !dockerEnabled}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      cpu_request_millicores: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <NumberInput
                label="CPU Limit (millicores)"
                value={policy.resources.cpu_limit_millicores ?? ""}
                min={1}
                placeholder="e.g. 1000"
                disabled={readOnly || !dockerEnabled}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      cpu_limit_millicores: optionalNumber(value),
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label="Memory Request"
                value={policy.resources.memory_request_bytes}
                placeholder="e.g. 2"
                disabled={readOnly || !dockerEnabled}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      memory_request_bytes: value,
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label="Memory Limit"
                value={policy.resources.memory_limit_bytes}
                placeholder="e.g. 4"
                disabled={readOnly || !dockerEnabled}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      memory_limit_bytes: value,
                    },
                  })
                }
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label="Ephemeral storage Request and Limit"
                description="Covers the DIND container filesystem and logs; Docker data capacity is configured separately above."
                value={policy.resources.ephemeral_storage_bytes}
                placeholder="e.g. 16"
                required={dockerEnabled}
                disabled={readOnly || !dockerEnabled}
                onChange={(value) =>
                  onChange({
                    ...policy,
                    resources: {
                      ...policy.resources,
                      ephemeral_storage_bytes: value,
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
          <Stack gap={2}>
            <Text fw={600}>Workspace storage</Text>
            <Text size="sm" c="dimmed">
              Persistent storage for files in the Agent Workspace. PVC expansion
              is automatic; a smaller value takes effect only after the PVC is
              deleted and recreated.
            </Text>
          </Stack>
          <ByteSizeInput
            label="Persistent Workspace PVC size"
            value={policy.resources.persistent_storage_bytes}
            placeholder="e.g. 20"
            disabled={readOnly}
            onChange={(value) =>
              onChange({
                ...policy,
                resources: {
                  ...policy.resources,
                  persistent_storage_bytes: value,
                },
              })
            }
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap={2}>
          <Text fw={600}>Outbound network access</Text>
          <Text size="sm" c="dimmed">
            Runtimes can access all outbound IPv4 and IPv6 destinations. The
            installation-owned Kubernetes NetworkPolicy remains the hard cap and
            can block configured CIDR ranges.
          </Text>
        </Stack>
      </Paper>
    </Stack>
  );
}
