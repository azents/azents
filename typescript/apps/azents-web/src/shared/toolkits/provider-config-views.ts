import { z } from "zod/v4";
import { isString } from "../lib/unknown-value.ts";
import { normalizeGitHubUserCredentialEdits } from "./github-user-credentials.ts";
import { isGitHubUserMode } from "./github-user-oauth-state.ts";
import { isWizardMode } from "./github-wizard-state.ts";
import { getClusterCredentials, getClusters } from "./kubernetes-fields.ts";
import { getServiceAccountKey } from "./service-account-fields.ts";
import type { GitHubWizardMode } from "./github-wizard-state";

const text = z.string().catch("");
const timeout = z
  .custom<number>((value) => typeof value === "number")
  .catch(30);
const awsSchema = z.object({
  region: z.string().catch("us-east-1"),
  role_arn: text,
  external_id: text,
  timeout,
});
const gcpServices = new Set([
  "logging",
  "monitoring",
  "gke",
  "compute",
  "cloud_run",
  "cloud_sql",
  "bigquery",
]);
function services(fallback: string[]): z.ZodType<string[]> {
  return z.preprocess(
    (value) =>
      Array.isArray(value)
        ? [
            ...new Set(
              value.filter(isString).filter((item) => gcpServices.has(item)),
            ),
          ]
        : fallback,
    z.array(z.string()),
  );
}
const gcpSchema = z.object({
  project_id: text,
  services: services(["logging", "monitoring"]),
  writable_services: services([]),
  timeout,
});
const googleAnalyticsSchema = z.object({ default_property_id: text, timeout });
const kubernetesSchema = z.object({
  read_only: z.boolean().catch(true),
  allowed_namespaces: z.preprocess(
    (value) => (Array.isArray(value) ? value.filter(isString) : null),
    z.array(z.string()).nullable(),
  ),
  denied_kinds: z.array(z.string()).catch(["Secret"]),
  timeout,
});
export const SENTRY_SKILLS = [
  "inspect",
  "seer",
  "docs",
  "triage",
  "manage",
] as const;
export type SentrySkill = (typeof SENTRY_SKILLS)[number];
const sentrySkill = z.enum(SENTRY_SKILLS);
const sentrySchema = z.object({
  timeout,
  enabled_skills: z.preprocess(
    (value) =>
      Array.isArray(value)
        ? value.filter(
            (item): item is SentrySkill => sentrySkill.safeParse(item).success,
          )
        : ["inspect", "seer"],
    z.array(sentrySkill),
  ),
});
const notionSchema = z.object({ timeout });
const awsCredentialsSchema = z.object({ access_key_id: text });
const serviceAccountCredentialsSchema = z.object({
  service_account_key: z
    .unknown()
    .optional()
    .transform((value) => {
      const key = getServiceAccountKey(value);
      const email = z.object({ client_email: z.string() }).safeParse(key);
      return email.success ? email.data.client_email : null;
    }),
});

/** Project consumed fields once; callers keep their opaque original solely for egress. */
export function projectAwsFields(
  config: unknown,
  credentials: unknown,
): AwsFieldsView {
  const decoded = awsSchema.parse(config);
  const access = awsCredentialsSchema.safeParse(credentials);
  return {
    ...decoded,
    accessKeyId: access.success ? access.data.access_key_id : "",
  };
}
export type AwsFieldsView = z.infer<typeof awsSchema> & { accessKeyId: string };
function clientEmail(credentials: unknown): string | null {
  const result = serviceAccountCredentialsSchema.safeParse(credentials);
  return result.success ? result.data.service_account_key : null;
}
export function projectGcpFields(
  config: unknown,
  credentials: unknown,
): GcpFieldsView {
  return { ...gcpSchema.parse(config), clientEmail: clientEmail(credentials) };
}
export type GcpFieldsView = z.infer<typeof gcpSchema> & {
  clientEmail: string | null;
};
export function projectGoogleAnalyticsFields(
  config: unknown,
  credentials: unknown,
): GoogleAnalyticsFieldsView {
  return {
    ...googleAnalyticsSchema.parse(config),
    clientEmail: clientEmail(credentials),
  };
}
export type GoogleAnalyticsFieldsView = z.infer<
  typeof googleAnalyticsSchema
> & { clientEmail: string | null };
export function projectKubernetesFields(
  config: Record<string, unknown>,
  credentials: Record<string, unknown> | null,
): KubernetesFieldsView {
  return {
    ...kubernetesSchema.parse(config),
    clusters: getClusters(config),
    clusterCredentials: getClusterCredentials(credentials),
  };
}
export type KubernetesFieldsView = z.infer<typeof kubernetesSchema> & {
  clusters: ReturnType<typeof getClusters>;
  clusterCredentials: ReturnType<typeof getClusterCredentials>;
};
export function projectNotionFields(config: unknown): NotionFieldsView {
  return notionSchema.parse(config);
}
export type NotionFieldsView = z.infer<typeof notionSchema>;
export function projectSentryFields(config: unknown): SentryFieldsView {
  return sentrySchema.parse(config);
}
export type SentryFieldsView = z.infer<typeof sentrySchema>;

const reviewSettingsSchema = z.object({
  toolsets: z.preprocess(
    (value) =>
      Array.isArray(value)
        ? value.filter(isString)
        : ["repos", "issues", "pull_requests", "users"],
    z.array(z.string()),
  ),
  timeout,
  inject_runtime_environment: z
    .unknown()
    .optional()
    .transform((value) => value === true),
});
export function projectGitHubReviewSettings(
  config: unknown,
): z.infer<typeof reviewSettingsSchema> {
  return reviewSettingsSchema.parse(config);
}

const githubAuthEvidenceSchema = z.object({
  github_auth_type: z
    .unknown()
    .optional()
    .transform((value) => ({
      savedDisplay: String(value),
      byoaUser: value === "github_app_user",
      userMode:
        value === "github_app_user" || value === "github_app_platform_user",
      platformUser: value === "github_app_platform_user",
    })),
});
/** Auth decisions keep exact historical discriminators, independently of form defaults. */
export function projectGitHubAuthEvidence(config: unknown): GitHubAuthEvidence {
  return githubAuthEvidenceSchema.parse(config).github_auth_type;
}
export type GitHubAuthEvidence = z.infer<
  typeof githubAuthEvidenceSchema
>["github_auth_type"];

const githubWizardModeSchema = z.object({
  github_auth_type: z
    .unknown()
    .optional()
    .transform((value) => (isWizardMode(value) ? value : null)),
});
const githubUserModeSchema = z.object({
  github_auth_type: z
    .unknown()
    .optional()
    .transform((value) => isGitHubUserMode(value)),
});
/** Management consumes only mode authority, without coercing opaque display values. */
export function projectGitHubUserMode(config: unknown): boolean {
  return githubUserModeSchema.parse(config).github_auth_type;
}

/** Resume only the five current Wizard modes; all other values require restart. */
export function projectGitHubWizardMode(
  config: unknown,
): GitHubWizardMode | null {
  return githubWizardModeSchema.parse(config).github_auth_type;
}

/** Boundary equality retains unknown provider discriminators without interpreting them downstream. */
export function gitHubAuthChanged(saved: unknown, current: unknown): boolean {
  const record = z.object({ github_auth_type: z.unknown().optional() });
  const previous = record.parse(saved);
  const next = record.parse(current);
  return previous.github_auth_type !== next.github_auth_type;
}

export interface GitHubFormRegistration {
  savedAuthType?: string;
  savedUserMode: boolean;
  registrationDirty: boolean;
}
export function projectGitHubFormRegistration(
  saved: Record<string, unknown> | null,
  current: Record<string, unknown>,
  credentials: Record<string, unknown> | null,
): GitHubFormRegistration {
  const previous = saved == null ? null : projectGitHubAuthEvidence(saved);
  const next = projectGitHubAuthEvidence(current);
  return {
    savedAuthType: previous?.savedDisplay,
    savedUserMode: previous?.userMode ?? false,
    registrationDirty:
      saved != null &&
      (gitHubAuthChanged(saved, current) ||
        (!next.platformUser &&
          normalizeGitHubUserCredentialEdits(credentials) != null)),
  };
}
