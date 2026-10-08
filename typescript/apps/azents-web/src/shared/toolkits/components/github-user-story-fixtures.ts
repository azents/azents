import type { GitHubUserAuthorizationProps } from "./GitHubUserAuthorization";
import type {
  GitHubUserConnectionSummary,
  GitHubUserInstallation,
} from "@azents/public-client";

export const githubUserConnection: GitHubUserConnectionSummary = {
  id: "connection-current",
  account_id: 101,
  account_login: "connected-user",
  account_avatar_url: null,
  app_id: "42",
  source: "byoa_user",
  status: "connected",
  failure_reason: null,
};
export const githubUserOwners: GitHubUserInstallation[] = [
  {
    installation_id: 1,
    app_id: 42,
    account_login: "connected-user",
    account_type: "User",
    account_avatar_url: null,
    app_permissions: { contents: "read" },
    repositories: [
      {
        repository_id: 1,
        owner_login: "connected-user",
        name: "personal-notes",
        full_name: "connected-user/personal-notes",
        private: true,
        permissions: { read: true, write: false, admin: null },
      },
    ],
    repositories_complete: true,
    failure_reason: null,
  },
  {
    installation_id: 2,
    app_id: 42,
    account_login: "research-team",
    account_type: "Organization",
    account_avatar_url: null,
    app_permissions: { contents: "write" },
    repositories: [
      {
        repository_id: 2,
        owner_login: "research-team",
        name: "shared-project",
        full_name: "research-team/shared-project",
        private: true,
        permissions: { read: true, write: null, admin: null },
      },
    ],
    repositories_complete: false,
    failure_reason: null,
  },
  {
    installation_id: 3,
    app_id: 42,
    account_login: "restricted-team",
    account_type: "Organization",
    account_avatar_url: null,
    app_permissions: {},
    repositories: [],
    repositories_complete: false,
    failure_reason: "target_denied",
  },
];
export const githubUserAuthorizationFixture: GitHubUserAuthorizationProps = {
  setup: { type: "IDLE" },
  operation: { type: "IDLE" },
  access: { type: "IDLE" },
  status: {
    type: "READY",
    connection: githubUserConnection,
  },
  currentConnection: githubUserConnection,
  registrationDirty: false,
  sharingScope: "workspace_shared",
  onStart: () => {},
  onCancel: () => {},
  onConfirm: () => {},
  onRequestDisconnect: () => {},
  onCancelDisconnect: () => {},
  onDisconnect: () => {},
  onRetryStatus: () => {},
  onRecheckAccess: () => {},
  onMoreAccess: () => {},
};
