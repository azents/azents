import { getString, isOneOf, isRecord } from "@/shared/lib/unknown-value";
import type { ClusterAuthType } from "./types";
type KubernetesConfig = Record<string, unknown>;
type KubernetesCredentials = Record<string, unknown> | null;

/** Cluster settings type */
export interface ClusterEntry {
  name: string;
  auth_type: ClusterAuthType;
  default_namespace: string;
  context: string | null;
  api_server: string | null;
  cluster_name: string | null;
  region: string | null;
  project_id: string | null;
}

/** Credential type by cluster */
export interface ClusterCredentialEntry {
  type: ClusterAuthType;
  kubeconfig_yaml?: string;
  token?: string;
  ca_cert?: string;
  aws_access_key_id?: string;
  aws_secret_access_key?: string;
  role_arn?: string;
  service_account_key?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Auth type options
// ---------------------------------------------------------------------------

export const AUTH_TYPE_OPTIONS = [
  { value: "kubeconfig", label: "Kubeconfig" },
  { value: "token", label: "Service Account Token" },
  { value: "eks", label: "AWS EKS (IAM)" },
  { value: "gke", label: "Google GKE (Service Account)" },
];

export const CLUSTER_AUTH_TYPES: readonly ClusterAuthType[] = [
  "kubeconfig",
  "token",
  "eks",
  "gke",
];

export const AUTH_TYPE_LABELS: Record<string, string> = {
  kubeconfig: "Kubeconfig",
  token: "Service Account Token",
  eks: "EKS",
  gke: "GKE",
};

// ---------------------------------------------------------------------------
// AWS region options (for EKS)
// ---------------------------------------------------------------------------

export const AWS_REGIONS = [
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

export const GKE_LOCATIONS = [
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
// Helpers: decode persisted cluster settings and credentials
// ---------------------------------------------------------------------------

export function getClusterAuthType(value: unknown): ClusterAuthType | null {
  return isOneOf(value, CLUSTER_AUTH_TYPES) ? value : null;
}

function getNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function decodeCluster(value: unknown): ClusterEntry | null {
  if (!isRecord(value) || typeof value.name !== "string") {
    return null;
  }

  return {
    name: value.name,
    auth_type: getClusterAuthType(value.auth_type) ?? "kubeconfig",
    default_namespace:
      getString(value.default_namespace, "default") || "default",
    context: getNullableString(value.context),
    api_server: getNullableString(value.api_server),
    cluster_name: getNullableString(value.cluster_name),
    region: getNullableString(value.region),
    project_id: getNullableString(value.project_id),
  };
}

export function getClusters(config: KubernetesConfig): ClusterEntry[] {
  if (!Array.isArray(config.clusters)) {
    return [];
  }

  return config.clusters.flatMap((cluster) => {
    const decoded = decodeCluster(cluster);
    return decoded ? [decoded] : [];
  });
}

function decodeClusterCredential(
  value: unknown,
): ClusterCredentialEntry | null {
  if (!isRecord(value)) {
    return null;
  }

  const type = getClusterAuthType(value.type);
  if (!type) {
    return null;
  }

  const credential: ClusterCredentialEntry = { type };
  const kubeconfigYaml = getNullableString(value.kubeconfig_yaml);
  const token = getNullableString(value.token);
  const caCert = getNullableString(value.ca_cert);
  const awsAccessKeyId = getNullableString(value.aws_access_key_id);
  const awsSecretAccessKey = getNullableString(value.aws_secret_access_key);
  const roleArn = getNullableString(value.role_arn);

  if (kubeconfigYaml !== null) {
    credential.kubeconfig_yaml = kubeconfigYaml;
  }
  if (token !== null) {
    credential.token = token;
  }
  if (caCert !== null) {
    credential.ca_cert = caCert;
  }
  if (awsAccessKeyId !== null) {
    credential.aws_access_key_id = awsAccessKeyId;
  }
  if (awsSecretAccessKey !== null) {
    credential.aws_secret_access_key = awsSecretAccessKey;
  }
  if (roleArn !== null) {
    credential.role_arn = roleArn;
  }
  if (
    value.service_account_key === null ||
    isRecord(value.service_account_key)
  ) {
    credential.service_account_key = value.service_account_key;
  }

  return credential;
}

export function getClusterCredentials(
  credentials: KubernetesCredentials,
): Record<string, ClusterCredentialEntry> {
  if (!isRecord(credentials?.clusters)) {
    return {};
  }

  const decoded: Record<string, ClusterCredentialEntry> = {};
  for (const [name, value] of Object.entries(credentials.clusters)) {
    const credential = decodeClusterCredential(value);
    if (credential) {
      decoded[name] = credential;
    }
  }
  return decoded;
}
