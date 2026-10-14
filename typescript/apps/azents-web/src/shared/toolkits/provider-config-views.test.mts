import assert from "node:assert/strict";
import test from "node:test";
import {
  projectAwsFields,
  projectGcpFields,
  projectGitHubAuthEvidence,
  projectGitHubFormRegistration,
  projectGitHubReviewSettings,
  projectGoogleAnalyticsFields,
  projectKubernetesFields,
  projectNotionFields,
  projectSentryFields,
} from "./provider-config-views.ts";
import { getServiceAccountKey } from "./service-account-fields.ts";
import type {
  GitHubUserCreationReview,
  ToolkitConfigResponse,
} from "@azents/public-client";

void test("complete persisted Toolkit responses and creation review project only consumed fields", () => {
  const shared = {
    id: "fixture-toolkit",
    workspace_id: "fixture-workspace",
    slug: "fixture",
    name: "Fixture",
    description: null,
    prompt: null,
    enabled: true,
    always_expose_tools: false,
    has_credentials: true,
    oauth_connection: null,
    authorization_state: null,
    github_user_connection: null,
    created_at: "2026-10-14T00:00:00Z",
    updated_at: "2026-10-14T00:00:00Z",
  };
  const persisted: ToolkitConfigResponse[] = [
    {
      ...shared,
      toolkit_type: "aws",
      config: {
        region: "us-east-1",
        role_arn: null,
        external_id: null,
        timeout: 35,
      },
    },
    {
      ...shared,
      toolkit_type: "gcp",
      config: {
        project_id: "fixture-project",
        services: ["logging", "monitoring"],
        writable_services: [],
        timeout: 35,
      },
    },
    {
      ...shared,
      toolkit_type: "google_analytics",
      config: { default_property_id: null, timeout: 35 },
    },
    {
      ...shared,
      toolkit_type: "kubernetes",
      config: {
        clusters: [
          {
            name: "fixture",
            auth_type: "token",
            api_server: "https://cluster.example",
            default_namespace: "default",
          },
        ],
        read_only: true,
        allowed_namespaces: null,
        denied_kinds: ["Secret"],
        timeout: 35,
      },
    },
    { ...shared, toolkit_type: "notion", config: { timeout: 35 } },
    {
      ...shared,
      toolkit_type: "sentry",
      config: { timeout: 35, enabled_skills: ["inspect", "seer"] },
    },
  ];
  for (const response of persisted) {
    const before = JSON.stringify(response);
    switch (response.toolkit_type) {
      case "aws":
        assert.equal(projectAwsFields(response.config, null).timeout, 35);
        break;
      case "gcp":
        assert.equal(projectGcpFields(response.config, null).timeout, 35);
        break;
      case "google_analytics":
        assert.equal(
          projectGoogleAnalyticsFields(response.config, null).timeout,
          35,
        );
        break;
      case "kubernetes":
        assert.equal(
          projectKubernetesFields(response.config, null).timeout,
          35,
        );
        break;
      case "notion":
        assert.equal(projectNotionFields(response.config).timeout, 35);
        break;
      case "sentry":
        assert.equal(projectSentryFields(response.config).timeout, 35);
        break;
    }
    assert.equal(JSON.stringify(response), before);
  }
  const review: GitHubUserCreationReview = {
    candidate: {
      attempt_id: "fixture-attempt",
      account_id: 42,
      account_login: "fixture-user",
      account_avatar_url: null,
      app_id: "123",
      source: "byoa_user",
      sharing_scope: "workspace_shared",
    },
    name: "Fixture",
    slug: "fixture",
    description: null,
    prompt: null,
    enabled: true,
    always_expose_tools: false,
    config: {
      github_auth_type: "github_app_user",
      toolsets: ["repos", "future"],
      timeout: 35,
      inject_runtime_environment: false,
    },
  };
  assert.deepEqual(projectGitHubReviewSettings(review.config), {
    toolsets: ["repos", "future"],
    timeout: 35,
    inject_runtime_environment: false,
  });
});

void test("persisted AWS known-field view preserves nullable roles, credential identity and opaque original", () => {
  const config = {
    region: "ap-northeast-2",
    role_arn: null,
    external_id: "external",
    timeout: 45,
    extension: { retained: true },
  };
  const credentials = {
    type: "aws",
    access_key_id: "fixture-access",
    secret_access_key: "fixture-secret",
    extension: null,
  };
  const before = JSON.stringify({ config, credentials });
  assert.deepEqual(projectAwsFields(config, credentials), {
    region: "ap-northeast-2",
    role_arn: "",
    external_id: "external",
    timeout: 45,
    accessKeyId: "fixture-access",
  });
  assert.equal(JSON.stringify({ config, credentials }), before);
  assert.deepEqual(
    projectAwsFields(
      { region: 1, role_arn: {}, external_id: false, timeout: "45" },
      null,
    ),
    {
      region: "us-east-1",
      role_arn: "",
      external_id: "",
      timeout: 30,
      accessKeyId: "",
    },
  );
  assert.deepEqual(projectAwsFields({}, { access_key_id: null }), {
    region: "us-east-1",
    role_arn: "",
    external_id: "",
    timeout: 30,
    accessKeyId: "",
  });
});
void test("persisted GCP service/credential matrix retains every current service, filters historical values and preserves key material", () => {
  const services = [
    "logging",
    "monitoring",
    "gke",
    "compute",
    "cloud_run",
    "cloud_sql",
    "bigquery",
  ];
  const key = {
    type: "service_account",
    project_id: "fixture-project",
    private_key_id: "fixture-id",
    private_key: "fixture-key",
    client_email: "fixture@project.iam.gserviceaccount.com",
    client_id: "123",
    auth_uri: "https://accounts.google.com/o/oauth2/auth",
    token_uri: "https://oauth2.googleapis.com/token",
    extension: { x: 1 },
  };
  const config = {
    project_id: "fixture-project",
    services,
    writable_services: ["compute", "bigquery"],
    timeout: 20,
    future: "retained",
  };
  const credentials = { service_account_key: key };
  const before = JSON.stringify({ config, credentials });
  assert.deepEqual(projectGcpFields(config, credentials), {
    project_id: "fixture-project",
    services,
    writable_services: ["compute", "bigquery"],
    timeout: 20,
    clientEmail: key.client_email,
  });
  assert.deepEqual(getServiceAccountKey(key), key);
  assert.equal(JSON.stringify({ config, credentials }), before);
  assert.deepEqual(
    projectGcpFields(
      {
        services: ["logging", "logging", "future", 2],
        writable_services: null,
      },
      { service_account_key: {} },
    ),
    {
      project_id: "",
      services: ["logging"],
      writable_services: [],
      timeout: 30,
      clientEmail: null,
    },
  );
  assert.deepEqual(projectGcpFields({}, null), {
    project_id: "",
    services: ["logging", "monitoring"],
    writable_services: [],
    timeout: 30,
    clientEmail: null,
  });
  assert.deepEqual(
    projectGcpFields(
      { services: [] },
      { service_account_key: { client_email: " " } },
    ).services,
    [],
  );
  for (const value of [
    null,
    [],
    {},
    { client_email: "" },
    { client_email: 2 },
  ]) {
    assert.equal(getServiceAccountKey(value), null);
  }
  assert.deepEqual(getServiceAccountKey({ client_email: " ", future: null }), {
    client_email: " ",
    future: null,
  });
});
void test("Google Analytics persisted nullable/default property and redacted credential view remains compatible", () => {
  assert.deepEqual(
    projectGoogleAnalyticsFields(
      { default_property_id: "123", timeout: 55 },
      {
        service_account_key: {
          client_email: "fixture@example",
          private_key: "retained",
        },
      },
    ),
    { default_property_id: "123", timeout: 55, clientEmail: "fixture@example" },
  );
  assert.deepEqual(
    projectGoogleAnalyticsFields(
      { default_property_id: null, timeout: null },
      { service_account_key: { private_key: null } },
    ),
    { default_property_id: "", timeout: 30, clientEmail: null },
  );
  assert.deepEqual(projectGoogleAnalyticsFields({}, null), {
    default_property_id: "",
    timeout: 30,
    clientEmail: null,
  });
});
void test("Kubernetes persisted multi-auth config and credential matrix keeps all current auth variants and null/namespace semantics", () => {
  const variants = ["kubeconfig", "token", "eks", "gke"];
  const config = {
    clusters: variants.map((auth_type) => ({
      name: auth_type,
      auth_type,
      default_namespace: "default",
      context: null,
      api_server: "https://cluster.example",
      cluster_name: "cluster",
      region: "us-east-1",
      project_id: "project",
      extension: "retained",
    })),
    read_only: false,
    allowed_namespaces: ["default", "ops"],
    denied_kinds: ["Secret", "ConfigMap"],
    timeout: 22,
    extension: true,
  };
  const credentials = {
    clusters: {
      kubeconfig: {
        type: "kubeconfig",
        kubeconfig_yaml: "fixture",
        extension: null,
      },
      token: { type: "token", token: "fixture", ca_cert: "ca" },
      eks: {
        type: "eks",
        aws_access_key_id: "fixture",
        aws_secret_access_key: "secret",
        role_arn: "arn:fixture",
      },
      gke: {
        type: "gke",
        service_account_key: {
          client_email: "fixture@example",
          private_key: "retained",
          future: true,
        },
      },
    },
  };
  const before = JSON.stringify({ config, credentials });
  const view = projectKubernetesFields(config, credentials);
  assert.deepEqual(
    view.clusters.map((cluster) => cluster.auth_type),
    variants,
  );
  assert.deepEqual(view.allowed_namespaces, ["default", "ops"]);
  assert.equal(view.read_only, false);
  assert.equal(view.timeout, 22);
  assert.deepEqual(view.denied_kinds, ["Secret", "ConfigMap"]);
  assert.deepEqual(
    view.clusterCredentials.gke?.service_account_key,
    credentials.clusters.gke.service_account_key,
  );
  assert.equal(JSON.stringify({ config, credentials }), before);
  assert.deepEqual(
    projectKubernetesFields(
      {
        clusters: [
          { name: "old", auth_type: "future", default_namespace: "" },
          null,
        ],
        read_only: "false",
        allowed_namespaces: ["ops", 1],
        denied_kinds: ["Secret", 1],
      },
      null,
    ),
    {
      read_only: true,
      allowed_namespaces: ["ops"],
      denied_kinds: ["Secret"],
      timeout: 30,
      clusters: [
        {
          name: "old",
          auth_type: "kubeconfig",
          default_namespace: "default",
          context: null,
          api_server: null,
          cluster_name: null,
          region: null,
          project_id: null,
        },
      ],
      clusterCredentials: {},
    },
  );
  assert.equal(
    projectKubernetesFields({ allowed_namespaces: null }, null)
      .allowed_namespaces,
    null,
  );
  assert.deepEqual(
    projectKubernetesFields({ allowed_namespaces: [], denied_kinds: [] }, null)
      .denied_kinds,
    [],
  );
});
void test("Notion and Sentry known views preserve current settings and historical filtering/defaults", () => {
  assert.deepEqual(projectNotionFields({ timeout: 42, extension: true }), {
    timeout: 42,
  });
  assert.deepEqual(projectNotionFields({ timeout: null }), { timeout: 30 });
  assert.deepEqual(
    projectSentryFields({
      timeout: 15,
      enabled_skills: ["inspect", "seer", "docs", "triage", "manage"],
      extension: true,
    }),
    {
      timeout: 15,
      enabled_skills: ["inspect", "seer", "docs", "triage", "manage"],
    },
  );
  assert.deepEqual(
    projectSentryFields({
      enabled_skills: ["inspect", "inspect", "future", 1],
    }),
    { timeout: 30, enabled_skills: ["inspect", "inspect"] },
  );
  assert.deepEqual(projectSentryFields({ enabled_skills: null }), {
    timeout: 30,
    enabled_skills: ["inspect", "seer"],
  });
  assert.deepEqual(
    projectSentryFields({ enabled_skills: [] }).enabled_skills,
    [],
  );
});
void test("resumed GitHub final-settings view filters toolsets and requires literal true without changing general form coercion", () => {
  assert.deepEqual(
    projectGitHubReviewSettings({
      toolsets: ["repos", "future", 1],
      timeout: 40,
      inject_runtime_environment: true,
      github_auth_type: "github_app_user",
      transport: null,
    }),
    {
      toolsets: ["repos", "future"],
      timeout: 40,
      inject_runtime_environment: true,
    },
  );
  for (const inject_runtime_environment of [false, "true", 1, null, void 0]) {
    assert.equal(
      projectGitHubReviewSettings({ inject_runtime_environment })
        .inject_runtime_environment,
      false,
    );
  }
  assert.deepEqual(
    projectGitHubReviewSettings({ toolsets: null, timeout: "30" }),
    {
      toolsets: ["repos", "issues", "pull_requests", "users"],
      timeout: 30,
      inject_runtime_environment: false,
    },
  );
  assert.deepEqual(projectGitHubReviewSettings({ toolsets: [] }).toolsets, []);
});
void test("saved/current auth evidence keeps exact known authority and opaque mismatch semantics", () => {
  for (const mode of [
    "pat",
    "github_app",
    "github_app_platform",
    "github_app_user",
    "github_app_platform_user",
  ]) {
    const config = { github_auth_type: mode, future: true };
    const view = projectGitHubFormRegistration(config, config, null);
    assert.equal(view.savedAuthType, mode);
    assert.equal(
      view.savedUserMode,
      mode === "github_app_user" || mode === "github_app_platform_user",
    );
    assert.equal(view.registrationDirty, false);
  }
  assert.equal(
    projectGitHubAuthEvidence({ github_auth_type: "future" }).userMode,
    false,
  );
  assert.equal(projectGitHubAuthEvidence({}).savedDisplay, "undefined");
  assert.equal(
    projectGitHubFormRegistration({ github_auth_type: null }, {}, null)
      .registrationDirty,
    true,
  );
  assert.equal(
    projectGitHubFormRegistration(
      { github_auth_type: "future" },
      { github_auth_type: "other" },
      null,
    ).registrationDirty,
    true,
  );
  assert.equal(
    projectGitHubFormRegistration(
      { github_auth_type: "github_app_user" },
      { github_auth_type: "github_app_user" },
      { type: "github_app_user", private_key: "" },
    ).registrationDirty,
    false,
  );
  assert.equal(
    projectGitHubFormRegistration(
      { github_auth_type: "github_app_user" },
      { github_auth_type: "github_app_user" },
      { type: "github_app_user", private_key: null },
    ).registrationDirty,
    true,
  );
  assert.equal(
    projectGitHubFormRegistration(
      { github_auth_type: "github_app_platform_user" },
      { github_auth_type: "github_app_platform_user" },
      { type: "github_app_platform_user", future: true },
    ).registrationDirty,
    false,
  );
});
