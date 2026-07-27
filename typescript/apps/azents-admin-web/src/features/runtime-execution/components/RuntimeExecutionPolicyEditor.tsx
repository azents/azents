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
  updateRuntimeExecutionDockerCapability,
  updateRuntimeExecutionNetworkMode,
} from "../runtimeExecutionPresentation";
import { ByteSizeInput } from "./ByteSizeInput";
import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionNetworkMode,
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

const NETWORK_MODE_OPTIONS: {
  value: RuntimeExecutionNetworkMode;
  label: string;
}[] = [
  { value: "none", label: "System traffic only" },
  { value: "restricted", label: "Allowlist (selected IP ranges)" },
  { value: "direct", label: "All IP addresses" },
];

function networkModeDescription(mode: RuntimeExecutionNetworkMode): string {
  switch (mode) {
    case "none":
      return "Allows only DNS and the Runtime Control connection required by the platform. Blocks all other outbound traffic.";
    case "direct":
      return "Allows outbound traffic to all IPv4 and IPv6 addresses except the blocked CIDR ranges below.";
    case "restricted":
      return "Allows only the IPv4 and IPv6 CIDR ranges listed below, excluding blocked ranges.";
  }
}

export function RuntimeExecutionPolicyEditor({
  policy,
  capabilities,
  readOnly = false,
  onChange,
}: RuntimeExecutionPolicyEditorProps): React.ReactElement {
  const dockerEnabled =
    policy.image_build.enabled || policy.container_run.enabled;
  const temporaryDockerStorageSupported =
    capabilities.storage_modes.includes("ephemeral");

  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>Docker</Text>
            <Text size="sm" c="dimmed">
              Configure Docker access inside the Runtime. Docker data is
              temporary and is deleted when the Runtime Pod is replaced.
            </Text>
          </Stack>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Checkbox
              label="Build Docker images"
              checked={policy.image_build.enabled}
              disabled={
                readOnly ||
                ((!capabilities.image_build ||
                  !temporaryDockerStorageSupported) &&
                  !policy.image_build.enabled)
              }
              onChange={(event) => {
                const enabled = event.currentTarget.checked;
                if (
                  enabled &&
                  (!capabilities.image_build ||
                    !temporaryDockerStorageSupported)
                ) {
                  return;
                }
                onChange(
                  updateRuntimeExecutionDockerCapability(
                    policy,
                    "image_build",
                    enabled,
                  ),
                );
              }}
            />
            <Checkbox
              label="Run Docker containers"
              checked={policy.container_run.enabled}
              disabled={
                readOnly ||
                ((!capabilities.container_run ||
                  !temporaryDockerStorageSupported) &&
                  !policy.container_run.enabled)
              }
              onChange={(event) => {
                const enabled = event.currentTarget.checked;
                if (
                  enabled &&
                  (!capabilities.container_run ||
                    !temporaryDockerStorageSupported)
                ) {
                  return;
                }
                onChange(
                  updateRuntimeExecutionDockerCapability(
                    policy,
                    "container_run",
                    enabled,
                  ),
                );
              }}
            />
            <Checkbox
              label="Use Docker Compose"
              checked={policy.compose.enabled}
              disabled={
                readOnly ||
                ((!capabilities.compose ||
                  !capabilities.container_run ||
                  !temporaryDockerStorageSupported) &&
                  !policy.compose.enabled)
              }
              onChange={(event) => {
                const enabled = event.currentTarget.checked;
                if (
                  enabled &&
                  (!capabilities.compose ||
                    !capabilities.container_run ||
                    !temporaryDockerStorageSupported)
                ) {
                  return;
                }
                onChange(
                  updateRuntimeExecutionDockerCapability(
                    policy,
                    "compose",
                    enabled,
                  ),
                );
              }}
            />
          </SimpleGrid>
          <Stack gap={2}>
            <Text size="sm" fw={500}>
              Nested container limits
            </Text>
            <Text size="xs" c="dimmed">
              Enforced across the Docker containers created inside this Runtime.
            </Text>
          </Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <NumberInput
              label="Aggregate PID limit"
              description="Optional maximum total PIDs across all nested Docker containers. Leave empty for unlimited."
              value={policy.resources.pids ?? ""}
              min={1}
              placeholder="e.g. 256"
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
            <NumberInput
              label="Container count limit"
              description="Optional maximum number of nested Docker containers. Leave empty for unlimited."
              value={policy.resources.container_count ?? ""}
              min={1}
              placeholder="e.g. 4"
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
          </SimpleGrid>
          <ByteSizeInput
            label="Temporary Docker storage capacity"
            description="Required for Docker images and containers."
            value={policy.engine_storage.capacity_bytes}
            required={dockerEnabled}
            placeholder="e.g. 8"
            disabled={readOnly || !dockerEnabled}
            onChange={(value) =>
              onChange({
                ...policy,
                engine_storage: {
                  ...policy.engine_storage,
                  capacity_bytes: value,
                },
              })
            }
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>Kubernetes resources</Text>
            <Text size="sm" c="dimmed">
              CPU and memory requests and limits are optional. Ephemeral storage
              uses one fixed value for both request and limit. Values are split
              between the Docker engine and policy-gateway containers.
            </Text>
          </Stack>
          <Grid>
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <NumberInput
                label="CPU request (millicores)"
                value={policy.resources.cpu_request_millicores ?? ""}
                min={1}
                placeholder="e.g. 500"
                disabled={readOnly}
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
                label="CPU limit (millicores)"
                value={policy.resources.cpu_limit_millicores ?? ""}
                min={1}
                placeholder="e.g. 1000"
                disabled={readOnly}
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
                label="Memory request"
                value={policy.resources.memory_request_bytes}
                placeholder="e.g. 2"
                disabled={readOnly}
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
                label="Memory limit"
                value={policy.resources.memory_limit_bytes}
                placeholder="e.g. 4"
                disabled={readOnly}
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
                label="Ephemeral storage"
                description="Applied as the same Kubernetes request and limit."
                value={policy.resources.ephemeral_storage_bytes}
                placeholder="e.g. 8"
                required={dockerEnabled}
                disabled={readOnly}
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
            <Grid.Col span={{ base: 12, sm: 6 }}>
              <ByteSizeInput
                label="Persistent workspace storage"
                description="PVC expansions apply automatically. A smaller value takes effect after the workspace PVC is deleted and recreated."
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
            </Grid.Col>
          </Grid>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Text fw={600}>Outbound network access</Text>
          <Select
            label="Access policy"
            description={networkModeDescription(policy.network_egress.mode)}
            data={NETWORK_MODE_OPTIONS}
            value={policy.network_egress.mode}
            disabled={readOnly}
            allowDeselect={false}
            onChange={(value) => {
              if (
                value === null ||
                !isSupportedRuntimeExecutionNetworkMode(value)
              ) {
                return;
              }
              onChange(updateRuntimeExecutionNetworkMode(policy, value));
            }}
          />
          {policy.network_egress.mode === "restricted" && (
            <Textarea
              label="Allowed IP ranges (CIDR)"
              description="One IPv4 or IPv6 CIDR per line, for example 140.82.112.0/20 or 2606:50c0::/32. Hostnames and URLs are not accepted."
              placeholder={"140.82.112.0/20\n2606:50c0::/32"}
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
          )}
          {policy.network_egress.mode !== "none" && (
            <Textarea
              label="Blocked IP ranges (CIDR)"
              description="One IPv4 or IPv6 CIDR per line. Traffic to these ranges is blocked even when otherwise allowed."
              placeholder={"10.0.0.0/8\nfd00::/8"}
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
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}
