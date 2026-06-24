"use client";

/**
 * GCP Toolkit settings form fields.
 *
 * Settings for Google Hosted Remote MCP server connection.
 * Provides Project ID, service selection, SA Key input, and connection test.
 */

import {
  Accordion,
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  Divider,
  FileInput,
  Group,
  List,
  NumberInput,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconCloudComputing,
  IconInfoCircle,
  IconPlugConnected,
  IconSettings,
  IconUpload,
} from "@tabler/icons-react";
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";

type GcpConfig = Record<string, unknown>;
type GcpCredentials = Record<string, unknown> | null;

interface GcpConfigFieldsProps {
  config: GcpConfig;
  onConfigChange: (config: GcpConfig) => void;
  credentials: GcpCredentials;
  onCredentialsChange: (credentials: GcpCredentials) => void;
  /** Existing credentials existence in edit mode */
  hasCredentials: boolean;
  handle: string;
  /** Existing toolkit config ID in edit mode */
  toolkitConfigId?: string;
}

// ---------------------------------------------------------------------------
// Service metadata
// ---------------------------------------------------------------------------

interface ServiceMeta {
  value: string;
  label: string;
  description: string;
  tier: "observability" | "infrastructure" | "data";
  hasWriteTools: boolean;
  readIamRole: string;
  writeIamRole: string | null;
  readRoleDescription: string;
  writeRoleDescription: string | null;
}

const SERVICES: ServiceMeta[] = [
  {
    value: "logging",
    label: "Cloud Logging",
    description: "Log queries and analysis",
    tier: "observability",
    hasWriteTools: false,
    readIamRole: "roles/logging.viewer",
    writeIamRole: null,
    readRoleDescription: "View logs",
    writeRoleDescription: null,
  },
  {
    value: "monitoring",
    label: "Cloud Monitoring",
    description: "Metrics, alerts, PromQL queries",
    tier: "observability",
    hasWriteTools: false,
    readIamRole: "roles/monitoring.viewer",
    writeIamRole: null,
    readRoleDescription: "View metrics and alert policies",
    writeRoleDescription: null,
  },
  {
    value: "gke",
    label: "GKE",
    description: "Kubernetes cluster and resource status",
    tier: "infrastructure",
    hasWriteTools: false,
    readIamRole: "roles/container.viewer",
    writeIamRole: null,
    readRoleDescription: "View GKE clusters and workloads",
    writeRoleDescription: null,
  },
  {
    value: "compute",
    label: "Compute Engine",
    description: "VM instances, disks, networks",
    tier: "infrastructure",
    hasWriteTools: true,
    readIamRole: "roles/compute.viewer",
    writeIamRole: "roles/compute.instanceAdmin.v1",
    readRoleDescription: "View VM instances and resources",
    writeRoleDescription: "Create, delete, start, stop VMs",
  },
  {
    value: "cloud_run",
    label: "Cloud Run",
    description: "Service status and deployment",
    tier: "infrastructure",
    hasWriteTools: true,
    readIamRole: "roles/run.viewer",
    writeIamRole: "roles/run.admin",
    readRoleDescription: "View Cloud Run services",
    writeRoleDescription: "Deploy and manage services",
  },
  {
    value: "cloud_sql",
    label: "Cloud SQL",
    description: "Database instances and SQL queries",
    tier: "data",
    hasWriteTools: true,
    readIamRole: "roles/cloudsql.viewer",
    writeIamRole: "roles/cloudsql.admin",
    readRoleDescription: "View database instances",
    writeRoleDescription: "Execute SQL, manage instances",
  },
  {
    value: "bigquery",
    label: "BigQuery",
    description: "Data analysis and SQL queries",
    tier: "data",
    hasWriteTools: true,
    readIamRole: "roles/bigquery.dataViewer",
    writeIamRole: "roles/bigquery.dataEditor",
    readRoleDescription: "View datasets and run queries",
    writeRoleDescription: "Create and modify tables",
  },
];

const TIER_LABELS: Record<string, string> = {
  observability: "Core Observability",
  infrastructure: "Infrastructure",
  data: "Data",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GcpConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  handle,
  toolkitConfigId,
}: GcpConfigFieldsProps): React.ReactElement {
  const projectId =
    typeof config.project_id === "string" ? config.project_id : "";
  const selectedServices = useMemo(
    () =>
      Array.isArray(config.services)
        ? (config.services as string[])
        : ["logging", "monitoring"],
    [config.services],
  );
  const writableServices = useMemo(
    () =>
      Array.isArray(config.writable_services)
        ? (config.writable_services as string[])
        : [],
    [config.writable_services],
  );
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;

  // SA Key state
  const [showKeyInput, setShowKeyInput] = useState(!hasCredentials);
  const clientEmail = useMemo(() => {
    if (!credentials) {
      return null;
    }
    const saKey = credentials.service_account_key;
    if (
      typeof saKey === "object" &&
      saKey !== null &&
      "client_email" in saKey
    ) {
      return (saKey as Record<string, unknown>).client_email as string;
    }
    return null;
  }, [credentials]);

  // Connection test
  const testConnectionMutation = trpc.toolkit.testConnection.useMutation();

  const handleTestConnection = useCallback((): void => {
    testConnectionMutation.mutate({
      handle,
      toolkitType: "gcp",
      toolkitConfigId: toolkitConfigId ?? null,
      config,
      credentials,
    });
  }, [handle, toolkitConfigId, config, credentials, testConnectionMutation]);

  // Service toggle
  const handleServiceToggle = useCallback(
    (serviceValue: string, checked: boolean): void => {
      const newServices = checked
        ? [...selectedServices, serviceValue]
        : selectedServices.filter((s) => s !== serviceValue);
      // Remove from writable too
      const newWritable = checked
        ? writableServices
        : writableServices.filter((s) => s !== serviceValue);
      onConfigChange({
        ...config,
        services: newServices,
        writable_services: newWritable,
      });
    },
    [config, selectedServices, writableServices, onConfigChange],
  );

  // Write access toggle
  const handleWritableToggle = useCallback(
    (serviceValue: string, checked: boolean): void => {
      const newWritable = checked
        ? [...writableServices, serviceValue]
        : writableServices.filter((s) => s !== serviceValue);
      onConfigChange({ ...config, writable_services: newWritable });
    },
    [config, writableServices, onConfigChange],
  );

  // Paste SA Key JSON
  const handleKeyPaste = useCallback(
    (value: string): void => {
      if (!value.trim()) {
        onCredentialsChange(null);
        return;
      }
      try {
        const parsed = JSON.parse(value) as Record<string, unknown>;
        onCredentialsChange({ service_account_key: parsed });
      } catch {
        // JSON parse failed — ignore because still typing
      }
    },
    [onCredentialsChange],
  );

  // SA Key file upload
  const handleFileUpload = useCallback(
    (file: File | null): void => {
      if (!file) {
        return;
      }
      const reader = new FileReader();
      reader.onload = (e): void => {
        const text = e.target?.result;
        if (typeof text === "string") {
          try {
            const parsed = JSON.parse(text) as Record<string, unknown>;
            onCredentialsChange({ service_account_key: parsed });
          } catch {
            // Invalid JSON file
          }
        }
      };
      reader.readAsText(file);
    },
    [onCredentialsChange],
  );

  // Calculate required IAM roles by selected service
  const requiredRoles = useMemo(() => {
    const roles: Array<{ role: string; description: string }> = [
      {
        role: "roles/mcp.toolUser",
        description: "Required for all GCP MCP tool calls",
      },
    ];
    for (const svc of SERVICES) {
      if (!selectedServices.includes(svc.value)) {
        continue;
      }
      roles.push({
        role: svc.readIamRole,
        description: svc.readRoleDescription,
      });
      if (
        svc.hasWriteTools &&
        writableServices.includes(svc.value) &&
        svc.writeIamRole
      ) {
        roles.push({
          role: svc.writeIamRole,
          description: svc.writeRoleDescription ?? "",
        });
      }
    }
    return roles;
  }, [selectedServices, writableServices]);

  // Group services by tier
  const tiers = useMemo(() => {
    const grouped: Record<string, ServiceMeta[]> = {};
    for (const svc of SERVICES) {
      const tier = svc.tier;
      if (!grouped[tier]) {
        grouped[tier] = [];
      }
      grouped[tier].push(svc);
    }
    return grouped;
  }, []);

  return (
    <Stack gap="md">
      {/* Project ID */}
      <TextInput
        label="Project ID"
        description="GCP project ID (e.g. my-production-project)"
        placeholder="my-production-project"
        required
        value={projectId}
        onChange={(e) =>
          onConfigChange({ ...config, project_id: e.currentTarget.value })
        }
        error={
          projectId.length > 0 &&
          !/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(projectId)
            ? "Project ID must be 6-30 characters, lowercase, start with letter"
            : null
        }
      />

      {/* Service selection */}
      <Stack gap="xs">
        <Text fw={500} size="sm">
          Services
        </Text>
        {Object.entries(tiers).map(([tier, services]) => (
          <Stack key={tier} gap={4}>
            <Text size="xs" c="dimmed" fw={600} tt="uppercase">
              {TIER_LABELS[tier] ?? tier}
            </Text>
            {services.map((svc) => {
              const isSelected = selectedServices.includes(svc.value);
              const isWritable = writableServices.includes(svc.value);
              return (
                <Stack key={svc.value} gap={2} ml="sm">
                  <Checkbox
                    label={
                      <Group gap="xs">
                        <Text size="sm">{svc.label}</Text>
                        <Text size="xs" c="dimmed">
                          {svc.description}
                        </Text>
                      </Group>
                    }
                    checked={isSelected}
                    onChange={(e) =>
                      handleServiceToggle(svc.value, e.currentTarget.checked)
                    }
                  />
                  {isSelected && svc.hasWriteTools && (
                    <Checkbox
                      ml="xl"
                      size="xs"
                      label={
                        <Group gap="xs">
                          <Text size="xs">Write access</Text>
                          <Badge size="xs" variant="light" color="orange">
                            {svc.writeRoleDescription}
                          </Badge>
                        </Group>
                      }
                      checked={isWritable}
                      onChange={(e) =>
                        handleWritableToggle(svc.value, e.currentTarget.checked)
                      }
                    />
                  )}
                </Stack>
              );
            })}
            <Divider my={4} />
          </Stack>
        ))}
      </Stack>

      {/* Service Account Key */}
      <Stack gap="xs">
        <Text fw={500} size="sm">
          Service Account Key
          <Text span c="red" ml={4}>
            *
          </Text>
        </Text>

        {clientEmail && !showKeyInput && (
          <Alert
            variant="light"
            color="blue"
            icon={<IconCloudComputing size={16} />}
          >
            <Group justify="space-between" align="center">
              <Text size="sm">
                Authenticated as <Code>{clientEmail}</Code>
              </Text>
              <Button
                size="xs"
                variant="subtle"
                onClick={() => setShowKeyInput(true)}
              >
                Replace Key
              </Button>
            </Group>
          </Alert>
        )}

        {showKeyInput && (
          <Stack gap="xs">
            <Textarea
              placeholder='Paste Service Account Key JSON here ({"type": "service_account", ...})'
              minRows={4}
              maxRows={8}
              autosize
              onChange={(e) => handleKeyPaste(e.currentTarget.value)}
            />
            <FileInput
              placeholder="Or upload .json file"
              accept=".json"
              leftSection={<IconUpload size={16} />}
              onChange={handleFileUpload}
            />
          </Stack>
        )}
      </Stack>

      {/* IAM role guide */}
      {selectedServices.length > 0 && (
        <Alert
          variant="light"
          color="blue"
          icon={<IconInfoCircle size={16} />}
          title="Required IAM Roles"
        >
          <Text size="xs" mb="xs">
            Grant these roles to your Service Account:
          </Text>
          <List size="xs" spacing={2}>
            {requiredRoles.map((r) => (
              <List.Item key={r.role}>
                <Group gap={4}>
                  <Code>{r.role}</Code>
                  <Text size="xs" c="dimmed">
                    — {r.description}
                  </Text>
                </Group>
              </List.Item>
            ))}
          </List>
        </Alert>
      )}

      {/* Connection test */}
      <Stack gap="xs">
        <Button
          variant="light"
          leftSection={<IconPlugConnected size={16} />}
          onClick={handleTestConnection}
          loading={testConnectionMutation.isPending}
          disabled={!projectId || !credentials}
        >
          Test Connection
        </Button>

        {testConnectionMutation.isSuccess && (
          <Alert
            variant="light"
            color={testConnectionMutation.data.success ? "green" : "red"}
            icon={
              testConnectionMutation.data.success ? (
                <IconCheck size={16} />
              ) : (
                <IconAlertTriangle size={16} />
              )
            }
          >
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {testConnectionMutation.data.message}
            </Text>
          </Alert>
        )}
      </Stack>

      {/* Advanced settings */}
      <Accordion variant="contained">
        <Accordion.Item value="advanced">
          <Accordion.Control icon={<IconSettings size={16} />}>
            Advanced Settings
          </Accordion.Control>
          <Accordion.Panel>
            <NumberInput
              label="Timeout (seconds)"
              description="MCP tool call timeout. Default 30 seconds."
              value={timeoutValue}
              onChange={(v) => onConfigChange({ ...config, timeout: v })}
              min={1}
              max={300}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
