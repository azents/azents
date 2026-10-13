import { trimToolkitWhitespace } from "../lib/toolkit-identifiers.ts";
import { isRecord } from "../lib/unknown-value.ts";
import type {
  GitHubSetupAppOutput,
  GitHubSetupVerificationOutput,
  GitHubUserCandidateSummary,
  GitHubUserCreationFinalSettings,
} from "@azents/public-client";

type GitHubSetupApp = NonNullable<GitHubSetupAppOutput["app"]>;
type GitHubSetupVerificationResult = GitHubSetupVerificationOutput;

export type GitHubWizardIdentity = "PERSONAL" | "APP";
export type GitHubWizardMode =
  | "pat"
  | "github_app"
  | "github_app_platform"
  | "github_app_user"
  | "github_app_platform_user";
export interface GitHubWizardCredentials {
  token: string;
  appId: string;
  privateKey: string;
  clientId: string;
  clientSecret: string;
  installationIds: string[];
}
export const GITHUB_FEATURE_GROUPS = [
  "repos",
  "issues",
  "pull_requests",
  "users",
  "actions",
  "code_security",
  "notifications",
  "orgs",
  "projects",
  "discussions",
];
export interface GitHubWizardSettings {
  name: string;
  slug: string;
  description: string;
  prompt: string;
  enabled: boolean;
  alwaysExposeTools: boolean;
  toolsets: string[];
  timeout: number;
  injectRuntimeEnvironment: boolean;
  runtimeRiskAcknowledged: boolean;
}
export const DEFAULT_GITHUB_WIZARD_SETTINGS: GitHubWizardSettings = {
  name: "",
  slug: "",
  description: "",
  prompt: "",
  enabled: true,
  alwaysExposeTools: false,
  toolsets: ["repos", "issues", "pull_requests", "users"],
  timeout: 30,
  injectRuntimeEnvironment: false,
  runtimeRiskAcknowledged: false,
};
export type GitHubWizardConnection =
  | { type: "INPUT" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "VERIFIED";
      verification: GitHubSetupVerificationResult;
      transport: "CURRENT" | "STALE" | "CHECKING" | "ERROR";
    }
  | {
      type: "CANDIDATE";
      candidate: GitHubUserCandidateSummary;
      app: GitHubWizardAppState;
    };
export type GitHubWizardAppState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; app: GitHubSetupApp };
export type GitHubWizardPublication =
  | { type: "IDLE" }
  | { type: "PENDING" }
  | { type: "SUCCESS" }
  | { type: "ERROR"; message: string }
  | { type: "UNCERTAIN" };
export type GitHubWizardAvailability =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      userAccount: "configured" | "incomplete" | "absent";
      installation: "configured" | "incomplete" | "absent";
      callbackUrl: string | null;
    };
export function wizardMode(
  identity: GitHubWizardIdentity,
  method: "PLATFORM" | "SELF_MANAGED" | "PAT",
): GitHubWizardMode | null {
  if (method === "PAT") {
    return identity === "PERSONAL" ? "pat" : null;
  }
  if (method === "PLATFORM") {
    return identity === "PERSONAL"
      ? "github_app_platform_user"
      : "github_app_platform";
  }
  return identity === "PERSONAL" ? "github_app_user" : "github_app";
}
export function wizardIdentity(mode: GitHubWizardMode): GitHubWizardIdentity {
  return mode === "github_app" || mode === "github_app_platform"
    ? "APP"
    : "PERSONAL";
}
export function isWizardMode(value: unknown): value is GitHubWizardMode {
  return (
    value === "pat" ||
    value === "github_app" ||
    value === "github_app_platform" ||
    value === "github_app_user" ||
    value === "github_app_platform_user"
  );
}
export function finalWizardSettings(
  settings: GitHubWizardSettings,
): GitHubUserCreationFinalSettings {
  return {
    name: trimToolkitWhitespace(settings.name) || null,
    slug: trimToolkitWhitespace(settings.slug) || null,
    description: settings.description || null,
    prompt: settings.prompt || null,
    enabled: settings.enabled,
    always_expose_tools: settings.alwaysExposeTools,
    toolsets: settings.toolsets,
    timeout: settings.timeout,
    inject_runtime_environment: settings.injectRuntimeEnvironment,
    runtime_risk_acknowledged: settings.runtimeRiskAcknowledged,
  };
}

export function wizardCandidateRequiresRestart(error: unknown): boolean {
  if (!isRecord(error) || !isRecord(error.data)) {
    return false;
  }
  return (
    error.data.code === "CONFLICT" ||
    error.data.code === "NOT_FOUND" ||
    error.data.code === "FORBIDDEN" ||
    error.data.code === "UNAUTHORIZED"
  );
}
