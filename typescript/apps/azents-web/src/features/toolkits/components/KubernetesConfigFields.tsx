"use client";

/**
 * Kubernetes Toolkit settings form fields.
 *
 * Provides multi-cluster management, credential input by auth method, security settings, and connection test.
 * Supported auth methods: Kubeconfig, Service Account Token, AWS EKS (IAM), Google GKE (SA).
 */

import {
  Accordion,
  Alert,
  Button,
  Card,
  Checkbox,
  Code,
  Group,
  List,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconInfoCircle,
  IconPlugConnected,
  IconPlus,
  IconSettings,
  IconTrash,
} from "@tabler/icons-react";
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";

type KubernetesConfig = Record<string, unknown>;
type KubernetesCredentials = Record<string, unknown> | null;

/** Cluster settings type */
interface ClusterEntry {
  name: string;
  auth_type: "kubeconfig" | "token" | "eks" | "gke";
  default_namespace: string;
  context: string | null;
  api_server: string | null;
  cluster_name: string | null;
  region: string | null;
  project_id: string | null;
}

/** Credential type by cluster */
interface ClusterCredentialEntry {
  type: "kubeconfig" | "token" | "eks" | "gke";
  kubeconfig_yaml?: string;
  token?: string;
  ca_cert?: string;
  aws_access_key_id?: string;
  aws_secret_access_key?: string;
  role_arn?: string;
  service_account_key?: Record<string, unknown> | null;
}

interface KubernetesConfigFieldsProps {
  config: KubernetesConfig;
  onConfigChange: (config: KubernetesConfig) => void;
  credentials: KubernetesCredentials;
  onCredentialsChange: (credentials: KubernetesCredentials) => void;
  /** Existing credentials existence in edit mode */
  hasCredentials: boolean;
  handle: string;
  /** Existing toolkit config ID in edit mode */
  toolkitConfigId?: string;
}

// ---------------------------------------------------------------------------
// Auth type options
// ---------------------------------------------------------------------------

const AUTH_TYPE_OPTIONS = [
  { value: "kubeconfig", label: "Kubeconfig" },
  { value: "token", label: "Service Account Token" },
  { value: "eks", label: "AWS EKS (IAM)" },
  { value: "gke", label: "Google GKE (Service Account)" },
];

const AUTH_TYPE_LABELS: Record<string, string> = {
  kubeconfig: "Kubeconfig",
  token: "Service Account Token",
  eks: "EKS",
  gke: "GKE",
};

// ---------------------------------------------------------------------------
// AWS region options (for EKS)
// ---------------------------------------------------------------------------

const AWS_REGIONS = [
  { value: "us-east-1", label: "N. Virginia (us-east-1)" },
  { value: "us-east-2", label: "Ohio (us-east-2)" },
  { value: "us-west-1", label: "N. California (us-west-1)" },
  { value: "us-west-2", label: "Oregon (us-west-2)" },
  { value: "ap-northeast-1", label: "Tokyo (ap-northeast-1)" },
  { value: "ap-northeast-2", label: "Seoul (ap-northeast-2)" },
  { value: "ap-northeast-3", label: "Osaka (ap-northeast-3)" },
  { value: "ap-southeast-1", label: "Singapore (ap-southeast-1)" },
  { value: "ap-southeast-2", label: "Sydney (ap-southeast-2)" },
  { value: "ap-south-1", label: "Mumbai (ap-south-1)" },
  { value: "eu-central-1", label: "Frankfurt (eu-central-1)" },
  { value: "eu-west-1", label: "Ireland (eu-west-1)" },
  { value: "eu-west-2", label: "London (eu-west-2)" },
  { value: "eu-west-3", label: "Paris (eu-west-3)" },
  { value: "eu-north-1", label: "Stockholm (eu-north-1)" },
  { value: "sa-east-1", label: "Sao Paulo (sa-east-1)" },
  { value: "ca-central-1", label: "Canada Central (ca-central-1)" },
];

// ---------------------------------------------------------------------------
// GKE region options
// ---------------------------------------------------------------------------

const GKE_LOCATIONS = [
  { value: "asia-northeast3", label: "Seoul (asia-northeast3)" },
  { value: "asia-northeast1", label: "Tokyo (asia-northeast1)" },
  { value: "asia-northeast2", label: "Osaka (asia-northeast2)" },
  { value: "asia-east1", label: "Taiwan (asia-east1)" },
  { value: "asia-southeast1", label: "Singapore (asia-southeast1)" },
  { value: "us-central1", label: "Iowa (us-central1)" },
  { value: "us-east1", label: "South Carolina (us-east1)" },
  { value: "us-west1", label: "Oregon (us-west1)" },
  { value: "europe-west1", label: "Belgium (europe-west1)" },
  { value: "europe-west4", label: "Netherlands (europe-west4)" },
];

// ---------------------------------------------------------------------------
// Helper: extract clusters array from config
// ---------------------------------------------------------------------------

function getClusters(config: KubernetesConfig): ClusterEntry[] {
  return Array.isArray(config.clusters)
    ? (config.clusters as ClusterEntry[])
    : [];
}

function getClusterCredentials(
  credentials: KubernetesCredentials,
): Record<string, ClusterCredentialEntry> {
  if (!credentials) {
    return {};
  }
  const clusters = credentials.clusters;
  if (typeof clusters === "object" && clusters !== null) {
    return clusters as Record<string, ClusterCredentialEntry>;
  }
  return {};
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function KubernetesConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  handle,
  toolkitConfigId,
}: KubernetesConfigFieldsProps): React.ReactElement {
  // Set of cluster names selected for credential replacement in edit mode
  const [replacingCreds, setReplacingCreds] = useState<Set<string>>(new Set());

  // Derived state
  const clusters = useMemo(() => getClusters(config), [config]);
  const clusterCredentials = useMemo(
    () => getClusterCredentials(credentials),
    [credentials],
  );
  const readOnly =
    typeof config.read_only === "boolean" ? config.read_only : true;
  const allowedNamespaces = useMemo(
    () =>
      Array.isArray(config.allowed_namespaces)
        ? (config.allowed_namespaces as string[])
        : null,
    [config.allowed_namespaces],
  );
  const deniedKinds = useMemo(
    () =>
      Array.isArray(config.denied_kinds)
        ? (config.denied_kinds as string[])
        : ["Secret"],
    [config.denied_kinds],
  );
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;

  // Connection test
  const testConnectionMutation = trpc.toolkit.testConnection.useMutation();

  const handleTestConnection = useCallback((): void => {
    testConnectionMutation.mutate({
      handle,
      toolkitType: "kubernetes",
      toolkitConfigId: toolkitConfigId ?? null,
      config,
      credentials,
    });
  }, [handle, toolkitConfigId, config, credentials, testConnectionMutation]);

  // --- Cluster CRUD ---

  const handleAddCluster = useCallback((): void => {
    const newCluster: ClusterEntry = {
      name: "",
      auth_type: "kubeconfig",
      default_namespace: "default",
      context: null,
      api_server: null,
      cluster_name: null,
      region: null,
      project_id: null,
    };
    onConfigChange({ ...config, clusters: [...clusters, newCluster] });
  }, [config, clusters, onConfigChange]);

  const handleRemoveCluster = useCallback(
    (index: number): void => {
      const removedName = clusters[index]?.name;
      const newClusters = clusters.filter((_, i) => i !== index);
      onConfigChange({ ...config, clusters: newClusters });
      // Remove credential too
      if (removedName) {
        const newCreds = { ...clusterCredentials };
        delete newCreds[removedName];
        onCredentialsChange({ ...credentials, clusters: newCreds });
      }
    },
    [
      config,
      clusters,
      credentials,
      clusterCredentials,
      onConfigChange,
      onCredentialsChange,
    ],
  );

  const handleUpdateCluster = useCallback(
    (index: number, updates: Partial<ClusterEntry>): void => {
      const oldCluster = clusters[index];
      if (!oldCluster) {
        return;
      }
      const newCluster = { ...oldCluster, ...updates };
      const newClusters = clusters.map((c, i) =>
        i === index ? newCluster : c,
      );

      // Reset credential when auth type changes
      if (updates.auth_type && updates.auth_type !== oldCluster.auth_type) {
        const newCreds = { ...clusterCredentials };
        if (oldCluster.name) {
          delete newCreds[oldCluster.name];
        }
        if (newCluster.name) {
          newCreds[newCluster.name] = { type: updates.auth_type };
        }
        onCredentialsChange({ ...credentials, clusters: newCreds });
      }

      // Change credential key when name changes
      if ("name" in updates && updates.name !== oldCluster.name) {
        const newCreds = { ...clusterCredentials };
        const oldCred = oldCluster.name
          ? (newCreds[oldCluster.name] ?? null)
          : null;
        if (oldCluster.name) {
          delete newCreds[oldCluster.name];
        }
        if (updates.name) {
          newCreds[updates.name] = oldCred ?? { type: newCluster.auth_type };
        }
        onCredentialsChange({ ...credentials, clusters: newCreds });
      }

      onConfigChange({ ...config, clusters: newClusters });
    },
    [
      config,
      clusters,
      credentials,
      clusterCredentials,
      onConfigChange,
      onCredentialsChange,
    ],
  );

  const handleUpdateClusterCredential = useCallback(
    (clusterName: string, updates: Partial<ClusterCredentialEntry>): void => {
      const existing =
        clusterName in clusterCredentials
          ? clusterCredentials[clusterName]
          : { type: "kubeconfig" as const };
      const newCreds = {
        ...clusterCredentials,
        [clusterName]: { ...existing, ...updates },
      };
      onCredentialsChange({ ...credentials, clusters: newCreds });
    },
    [credentials, clusterCredentials, onCredentialsChange],
  );

  // --- Security settings ---

  const handleReadOnlyToggle = useCallback(
    (checked: boolean): void => {
      onConfigChange({ ...config, read_only: checked });
    },
    [config, onConfigChange],
  );

  const handleAllowedNamespacesChange = useCallback(
    (value: string): void => {
      if (!value.trim()) {
        onConfigChange({ ...config, allowed_namespaces: null });
        return;
      }
      const namespaces = value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      onConfigChange({ ...config, allowed_namespaces: namespaces });
    },
    [config, onConfigChange],
  );

  const handleDeniedKindsChange = useCallback(
    (value: string): void => {
      const kinds = value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      onConfigChange({ ...config, denied_kinds: kinds });
    },
    [config, onConfigChange],
  );

  // Auth type list used in current cluster (for permission guide display)
  const usedAuthTypes = useMemo(() => {
    const types = new Set<string>();
    for (const cluster of clusters) {
      types.add(cluster.auth_type);
    }
    return types;
  }, [clusters]);

  // Parse SA Key JSON (for GKE)
  const handleGkeKeyPaste = useCallback(
    (clusterName: string, value: string): void => {
      if (!value.trim()) {
        handleUpdateClusterCredential(clusterName, {
          service_account_key: null,
        });
        return;
      }
      try {
        const parsed = JSON.parse(value) as Record<string, unknown>;
        handleUpdateClusterCredential(clusterName, {
          service_account_key: parsed,
        });
      } catch {
        // JSON parse failed — ignore because still typing
      }
    },
    [handleUpdateClusterCredential],
  );

  return (
    <Stack gap="md">
      {/* Cluster list */}
      <Stack gap="xs">
        <Text fw={500} size="sm">
          Cluster
        </Text>

        {clusters.length === 0 && (
          <Text size="sm" c="dimmed">
            No Cluster is configured. Add a Cluster with the button below.
          </Text>
        )}

        {clusters.map((cluster, index) => (
          <Card key={index} withBorder padding="md">
            <Stack gap="sm">
              {/* Cluster header */}
              <Group justify="space-between">
                <Text fw={500} size="sm">
                  {cluster.name || "(Name unset)"}
                  {cluster.name && (
                    <Text span c="dimmed" size="xs" ml="xs">
                      {AUTH_TYPE_LABELS[cluster.auth_type] ?? cluster.auth_type}
                      {cluster.region ? ` (${cluster.region})` : ""}
                    </Text>
                  )}
                </Text>
                <Button
                  variant="subtle"
                  color="red"
                  size="xs"
                  leftSection={<IconTrash size={14} />}
                  onClick={() => handleRemoveCluster(index)}
                >
                  Delete
                </Button>
              </Group>

              {/* Cluster name */}
              <TextInput
                label="Cluster name"
                description="Identifier for agent to distinguish Cluster"
                placeholder="production-eks"
                required
                value={cluster.name}
                onChange={(e) =>
                  handleUpdateCluster(index, { name: e.currentTarget.value })
                }
              />

              {/* Default namespace */}
              <TextInput
                label="Default Namespace"
                description="Default value used when namespace is unspecified"
                placeholder="default"
                value={cluster.default_namespace}
                onChange={(e) =>
                  handleUpdateCluster(index, {
                    default_namespace: e.currentTarget.value || "default",
                  })
                }
              />

              {/* Authentication method selection */}
              <Select
                label="Authentication method"
                data={AUTH_TYPE_OPTIONS}
                value={cluster.auth_type}
                onChange={(v) => {
                  if (!v) {
                    return;
                  }
                  handleUpdateCluster(index, {
                    auth_type: v as ClusterEntry["auth_type"],
                  });
                }}
              />

              {/* Fields by auth type */}
              {(() => {
                // When existing credentials are stored on server and user has not selected replacement yet
                const credsSaved =
                  hasCredentials &&
                  !!cluster.name &&
                  !(cluster.name in clusterCredentials) &&
                  !replacingCreds.has(cluster.name);
                const handleReplace = (): void => {
                  setReplacingCreds((prev) => new Set(prev).add(cluster.name));
                };

                if (cluster.auth_type === "kubeconfig") {
                  return (
                    <Stack gap="xs">
                      <TextInput
                        label="Context"
                        description="Context name to use from kubeconfig (uses current-context if empty)"
                        placeholder="my-cluster-context"
                        value={cluster.context ?? ""}
                        onChange={(e) =>
                          handleUpdateCluster(index, {
                            context: e.currentTarget.value || null,
                          })
                        }
                      />
                      {credsSaved ? (
                        <Alert
                          variant="light"
                          color="blue"
                          icon={<IconInfoCircle size={16} />}
                        >
                          <Stack gap={4}>
                            <Text size="sm">Kubeconfig is configured.</Text>
                            <Button
                              size="xs"
                              variant="subtle"
                              onClick={handleReplace}
                            >
                              Replace credentials
                            </Button>
                          </Stack>
                        </Alert>
                      ) : (
                        <>
                          <Textarea
                            label="Kubeconfig YAML"
                            description="Paste full contents of kubeconfig file"
                            placeholder="apiVersion: v1&#10;kind: Config&#10;..."
                            required
                            minRows={6}
                            maxRows={12}
                            autosize
                            value={
                              clusterCredentials[cluster.name]
                                ?.kubeconfig_yaml ?? ""
                            }
                            onChange={(e) =>
                              handleUpdateClusterCredential(cluster.name, {
                                type: "kubeconfig",
                                kubeconfig_yaml: e.currentTarget.value,
                              })
                            }
                          />
                          <Alert
                            variant="light"
                            color="yellow"
                            icon={<IconAlertTriangle size={16} />}
                          >
                            <Text size="xs">
                              For security, kubeconfig containing{" "}
                              <Code>exec</Code> provider cannot be used. Only
                              static auth methods (token,
                              client-certificate-data) are supported.
                            </Text>
                          </Alert>
                        </>
                      )}
                    </Stack>
                  );
                }

                if (cluster.auth_type === "token") {
                  return (
                    <Stack gap="xs">
                      <TextInput
                        label="API Server URL"
                        description="Kubernetes API server address"
                        placeholder="https://kubernetes.example.com:6443"
                        required
                        value={cluster.api_server ?? ""}
                        onChange={(e) =>
                          handleUpdateCluster(index, {
                            api_server: e.currentTarget.value || null,
                          })
                        }
                      />
                      {credsSaved ? (
                        <Alert
                          variant="light"
                          color="blue"
                          icon={<IconInfoCircle size={16} />}
                        >
                          <Stack gap={4}>
                            <Text size="sm">
                              Service Account Token is configured.
                            </Text>
                            <Button
                              size="xs"
                              variant="subtle"
                              onClick={handleReplace}
                            >
                              Replace credentials
                            </Button>
                          </Stack>
                        </Alert>
                      ) : (
                        <>
                          <PasswordInput
                            label="Service Account Token"
                            description="Bearer token of Kubernetes Service Account"
                            placeholder="eyJhbGciOiJS..."
                            required
                            value={
                              clusterCredentials[cluster.name]?.token ?? ""
                            }
                            onChange={(e) =>
                              handleUpdateClusterCredential(cluster.name, {
                                type: "token",
                                token: e.currentTarget.value,
                              })
                            }
                          />
                          <Textarea
                            label="CA Certificate (optional)"
                            description="Base64-encoded CA certificate. Required when using self-signed certificate"
                            placeholder="LS0tLS1CRUdJTi..."
                            minRows={3}
                            maxRows={6}
                            autosize
                            value={
                              clusterCredentials[cluster.name]?.ca_cert ?? ""
                            }
                            onChange={(e) =>
                              handleUpdateClusterCredential(cluster.name, {
                                type: "token",
                                ca_cert: e.currentTarget.value || "",
                              })
                            }
                          />
                        </>
                      )}
                    </Stack>
                  );
                }

                if (cluster.auth_type === "eks") {
                  return (
                    <Stack gap="xs">
                      {credsSaved ? (
                        <Alert
                          variant="light"
                          color="blue"
                          icon={<IconInfoCircle size={16} />}
                        >
                          <Stack gap={4}>
                            <Text size="sm">
                              AWS credentials are configured.
                            </Text>
                            <Button
                              size="xs"
                              variant="subtle"
                              onClick={handleReplace}
                            >
                              Replace credentials
                            </Button>
                          </Stack>
                        </Alert>
                      ) : (
                        <>
                          <TextInput
                            label="Access Key ID"
                            placeholder="AKIA..."
                            required
                            value={
                              clusterCredentials[cluster.name]
                                ?.aws_access_key_id ?? ""
                            }
                            onChange={(e) =>
                              handleUpdateClusterCredential(cluster.name, {
                                type: "eks",
                                aws_access_key_id: e.currentTarget.value,
                              })
                            }
                          />
                          <PasswordInput
                            label="Secret Access Key"
                            placeholder="Enter secret access key"
                            required
                            value={
                              clusterCredentials[cluster.name]
                                ?.aws_secret_access_key ?? ""
                            }
                            onChange={(e) =>
                              handleUpdateClusterCredential(cluster.name, {
                                type: "eks",
                                aws_secret_access_key: e.currentTarget.value,
                              })
                            }
                          />
                          <TextInput
                            label="Role ARN (optional)"
                            description="Role to assume when cross-account access is required"
                            placeholder="arn:aws:iam::123456789012:role/EKSAccess"
                            value={
                              clusterCredentials[cluster.name]?.role_arn ?? ""
                            }
                            onChange={(e) =>
                              handleUpdateClusterCredential(cluster.name, {
                                type: "eks",
                                role_arn: e.currentTarget.value || "",
                              })
                            }
                          />
                        </>
                      )}
                      <Select
                        label="Region"
                        data={AWS_REGIONS}
                        value={cluster.region ?? "ap-northeast-2"}
                        onChange={(v) =>
                          handleUpdateCluster(index, {
                            region: v ?? "ap-northeast-2",
                          })
                        }
                        searchable
                        required
                      />
                      <TextInput
                        label="Cluster name (EKS)"
                        description="EKS Cluster name. Endpoint is automatically looked up through describe_cluster API"
                        placeholder="my-eks-cluster"
                        required
                        value={cluster.cluster_name ?? ""}
                        onChange={(e) =>
                          handleUpdateCluster(index, {
                            cluster_name: e.currentTarget.value || null,
                          })
                        }
                      />
                    </Stack>
                  );
                }

                // gke
                return (
                  <Stack gap="xs">
                    {credsSaved ? (
                      <Alert
                        variant="light"
                        color="blue"
                        icon={<IconInfoCircle size={16} />}
                      >
                        <Stack gap={4}>
                          <Text size="sm">
                            GCP Service Account Key is configured.
                          </Text>
                          <Button
                            size="xs"
                            variant="subtle"
                            onClick={handleReplace}
                          >
                            Replace credentials
                          </Button>
                        </Stack>
                      </Alert>
                    ) : (
                      <Textarea
                        label="Service Account Key JSON"
                        description="Paste full GCP Service Account Key JSON"
                        placeholder='{"type": "service_account", "project_id": "...", ...}'
                        required
                        minRows={4}
                        maxRows={8}
                        autosize
                        onChange={(e) =>
                          handleGkeKeyPaste(cluster.name, e.currentTarget.value)
                        }
                      />
                    )}
                    <TextInput
                      label="Project ID"
                      description="GCP project ID"
                      placeholder="my-gcp-project"
                      required
                      value={cluster.project_id ?? ""}
                      onChange={(e) =>
                        handleUpdateCluster(index, {
                          project_id: e.currentTarget.value || null,
                        })
                      }
                    />
                    <Select
                      label="Location"
                      description="Region or zone where GKE Cluster is located"
                      data={GKE_LOCATIONS}
                      value={cluster.region ?? ""}
                      onChange={(v) =>
                        handleUpdateCluster(index, { region: v ?? null })
                      }
                      searchable
                      required
                    />
                    <TextInput
                      label="Cluster name (GKE)"
                      description="GKE Cluster name. Endpoint is automatically looked up through GKE API"
                      placeholder="my-gke-cluster"
                      required
                      value={cluster.cluster_name ?? ""}
                      onChange={(e) =>
                        handleUpdateCluster(index, {
                          cluster_name: e.currentTarget.value || null,
                        })
                      }
                    />
                  </Stack>
                );
              })()}
            </Stack>
          </Card>
        ))}

        <Button
          variant="light"
          leftSection={<IconPlus size={16} />}
          onClick={handleAddCluster}
        >
          Add Cluster
        </Button>
      </Stack>

      {/* Security settings */}
      <Stack gap="xs">
        <Text fw={500} size="sm">
          Security settings
        </Text>
        <Checkbox
          label="Read-only mode (recommended)"
          description="When enabled, only lookup tools are provided. apply, delete, and exec tools are disabled."
          checked={readOnly}
          onChange={(e) => handleReadOnlyToggle(e.currentTarget.checked)}
        />
        <TextInput
          label="Namespace restriction (optional)"
          description="Enter allowed namespaces separated by commas. Leave empty to access all namespaces."
          placeholder="app, monitoring, default"
          value={allowedNamespaces ? allowedNamespaces.join(", ") : ""}
          onChange={(e) => handleAllowedNamespacesChange(e.currentTarget.value)}
        />
        <TextInput
          label="Blocked resource kinds"
          description="Comma-separated resource kinds to block access to. Default: Secret"
          placeholder="Secret"
          value={deniedKinds.join(", ")}
          onChange={(e) => handleDeniedKindsChange(e.currentTarget.value)}
        />
      </Stack>

      {/* Permission guide (dynamic display by auth type) */}
      {clusters.length > 0 && (
        <Alert
          variant="light"
          color="blue"
          icon={<IconInfoCircle size={16} />}
          title="Required permission guide"
        >
          <Stack gap="xs">
            {usedAuthTypes.has("eks") && (
              <>
                <Text size="xs" fw={600}>
                  EKS IAM permissions:
                </Text>
                <List size="xs" spacing={2}>
                  <List.Item>
                    <Code>eks:DescribeCluster</Code>
                    <Text span size="xs" c="dimmed">
                      {" "}
                      — Cluster endpoint lookup
                    </Text>
                  </List.Item>
                  <List.Item>
                    <Code>eks:ListClusters</Code>
                    <Text span size="xs" c="dimmed">
                      {" "}
                      — Cluster list scan
                    </Text>
                  </List.Item>
                  <List.Item>
                    <Code>sts:GetCallerIdentity</Code>
                    <Text span size="xs" c="dimmed">
                      {" "}
                      — K8s auth token creation
                    </Text>
                  </List.Item>
                </List>
              </>
            )}

            {usedAuthTypes.has("gke") && (
              <>
                <Text size="xs" fw={600}>
                  GKE IAM roles:
                </Text>
                <List size="xs" spacing={2}>
                  <List.Item>
                    <Code>roles/container.clusterViewer</Code>
                    <Text span size="xs" c="dimmed">
                      {" "}
                      — Cluster information lookup
                    </Text>
                  </List.Item>
                </List>
              </>
            )}

            <Text size="xs" fw={600}>
              K8s RBAC ({readOnly ? "read-only" : "read-write"} mode):
            </Text>
            <List size="xs" spacing={2}>
              <List.Item>
                <Code>get, list, watch</Code>
                <Text span size="xs" c="dimmed">
                  {" "}
                  — Resource lookup
                </Text>
              </List.Item>
              <List.Item>
                <Code>pods/log</Code>
                <Text span size="xs" c="dimmed">
                  {" "}
                  — Log lookup
                </Text>
              </List.Item>
              {!readOnly && (
                <>
                  <List.Item>
                    <Code>create, update, patch, delete</Code>
                    <Text span size="xs" c="dimmed">
                      {" "}
                      — Resource changes
                    </Text>
                  </List.Item>
                  <List.Item>
                    <Code>pods/exec</Code>
                    <Text span size="xs" c="dimmed">
                      {" "}
                      — Command execution
                    </Text>
                  </List.Item>
                </>
              )}
            </List>

            <Text size="xs" c="dimmed" mt="xs">
              Setup guide:{" "}
              <Text
                component="a"
                href="https://docs.aws.amazon.com/eks/latest/userguide/grant-k8s-access.html"
                target="_blank"
                rel="noopener noreferrer"
                size="xs"
                c="blue"
                td="underline"
              >
                EKS IAM Access
              </Text>
              {" | "}
              <Text
                component="a"
                href="https://cloud.google.com/kubernetes-engine/docs/how-to/api-server-authentication"
                target="_blank"
                rel="noopener noreferrer"
                size="xs"
                c="blue"
                td="underline"
              >
                GKE Authentication
              </Text>
            </Text>
          </Stack>
        </Alert>
      )}

      {/* Advanced settings */}
      <Accordion variant="contained">
        <Accordion.Item value="advanced">
          <Accordion.Control icon={<IconSettings size={16} />}>
            Advanced settings
          </Accordion.Control>
          <Accordion.Panel>
            <NumberInput
              label="Timeout (seconds)"
              description="K8s API request timeout. Default 30 seconds."
              value={timeoutValue}
              onChange={(v) => onConfigChange({ ...config, timeout: v })}
              min={1}
              max={300}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      {/* Connection test (existing toolkit only) */}
      {toolkitConfigId && (
        <Stack gap="xs">
          <Button
            variant="light"
            leftSection={<IconPlugConnected size={16} />}
            onClick={handleTestConnection}
            loading={testConnectionMutation.isPending}
            disabled={testConnectionMutation.isPending || clusters.length === 0}
          >
            Connection test
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
      )}
    </Stack>
  );
}
