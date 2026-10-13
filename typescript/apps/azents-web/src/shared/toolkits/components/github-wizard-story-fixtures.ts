import { fn } from "storybook/test";
import { DEFAULT_GITHUB_WIZARD_SETTINGS } from "../github-wizard-state";
import type { GitHubWizardProps } from "./GitHubWizard";

export const wizardStoryProps: GitHubWizardProps = {
  embedded: false,
  sharingScope: "workspace_shared",
  identity: null,
  mode: null,
  availability: {
    type: "READY",
    userAccount: "configured",
    installation: "configured",
    callbackUrl: "https://azents.example/oauth/github/callback",
  },
  platformApp: {
    type: "READY",
    app: { app_id: "123", name: "Azents Test App", slug: "azents-test-app" },
  },
  connection: { type: "INPUT" },
  candidate: null,
  credentials: {
    token: "",
    appId: "",
    privateKey: "",
    clientId: "",
    clientSecret: "",
    installationIds: [],
  },
  settings: DEFAULT_GITHUB_WIZARD_SETTINGS,
  stage: "CONNECTION",
  publication: { type: "IDLE" },
  installationState: { type: "IDLE" },
  canContinue: false,
  onIdentity: fn(),
  onMode: fn(),
  onCredentials: fn(),
  onSettings: fn(),
  onConnect: fn(),
  onRetryMetadata: fn(),
  onRetryAvailability: fn(),
  onRetryPlatformMetadata: fn(),
  onContinue: fn(),
  onReset: fn(),
  onClose: fn(),
  onInspect: fn(),
  onPublish: fn(),
  onConnectInstallations: fn(),
  onInstallApp: fn(),
};
export const wizardCandidateConnection = {
  type: "CANDIDATE",
  candidate: {
    attempt_id: "attempt",
    account_id: 42,
    account_login: "fixture-user",
    account_avatar_url: null,
    app_id: "123",
    source: "byoa_user",
    sharing_scope: "workspace_shared",
  },
  app: {
    type: "READY",
    app: { app_id: "123", name: "Azents Test App", slug: "azents-test-app" },
  },
} satisfies GitHubWizardProps["connection"];
export const wizardReviewProps: GitHubWizardProps = {
  ...wizardStoryProps,
  identity: "PERSONAL",
  mode: "github_app_user",
  connection: wizardCandidateConnection,
  stage: "REVIEW",
  canContinue: true,
  settings: {
    ...DEFAULT_GITHUB_WIZARD_SETTINGS,
    name: "Development GitHub",
    toolsets: ["repos", "issues", "actions"],
  },
};
