import assert from "node:assert/strict";
import test from "node:test";
import {
  canAuthorizeAgentToolkitOAuth,
  decodeAgentToolkitOAuthCallback,
  projectAgentToolkitManagementState,
} from "../agentToolkitManagementState.ts";
import type { AgentToolkitManagementItemResponse } from "@azents/public-client";

const sentry: AgentToolkitManagementItemResponse = {
  ownership_scope: "workspace_shared",
  agent_toolkit_id: "attachment-1",
  readiness: "authorization_required",
  toolkit: {
    id: "toolkit-1",
    workspace_id: "workspace-1",
    toolkit_type: "sentry",
    slug: "sentry",
    name: "Sentry",
    description: null,
    config: {},
    prompt: null,
    has_credentials: false,
    enabled: true,
    always_expose_tools: false,
    oauth_connection: null,
    authorization_state: null,
    created_at: "2026-09-07T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
  },
};

void test("offers inline OAuth only for authorized managers and OAuth toolkits requiring it", () => {
  assert.equal(canAuthorizeAgentToolkitOAuth(sentry, true), true);
  assert.equal(canAuthorizeAgentToolkitOAuth(sentry, false), false);
  assert.equal(
    canAuthorizeAgentToolkitOAuth(
      { ...sentry, ownership_scope: "agent_only", agent_toolkit_id: null },
      false,
    ),
    true,
  );
  assert.equal(
    canAuthorizeAgentToolkitOAuth(
      { ...sentry, toolkit: { ...sentry.toolkit, toolkit_type: "github" } },
      true,
    ),
    false,
  );
  assert.equal(
    canAuthorizeAgentToolkitOAuth({ ...sentry, readiness: "ready" }, true),
    false,
  );
  assert.equal(
    canAuthorizeAgentToolkitOAuth(
      {
        ...sentry,
        toolkit: {
          ...sentry.toolkit,
          toolkit_type: "mcp",
          config: { auth_type: "none" },
        },
      },
      true,
    ),
    false,
  );
});

void test("accepts only typed same-origin results from the popup that started authorization", () => {
  const popup = {};
  const callback = {
    source: popup,
    origin: "https://azents.example",
    data: { type: "azents-oauth-callback", success: true },
  };
  assert.equal(
    decodeAgentToolkitOAuthCallback(callback, callback.origin, popup),
    "SUCCESS",
  );
  assert.equal(
    decodeAgentToolkitOAuthCallback(
      { ...callback, data: { ...callback.data, success: false } },
      callback.origin,
      popup,
    ),
    "FAILURE",
  );
  assert.equal(
    decodeAgentToolkitOAuthCallback(callback, callback.origin, null),
    null,
  );
  assert.equal(
    decodeAgentToolkitOAuthCallback(
      callback,
      "https://elsewhere.example",
      popup,
    ),
    null,
  );
  assert.equal(
    decodeAgentToolkitOAuthCallback(callback, callback.origin, {}),
    null,
  );
  assert.equal(
    decodeAgentToolkitOAuthCallback(
      { ...callback, data: { ...callback.data, success: "true" } },
      callback.origin,
      popup,
    ),
    null,
  );
});

void test("projects loading and error states without toolkit data", () => {
  assert.deepEqual(
    projectAgentToolkitManagementState({
      loading: true,
      error: null,
    }),
    { type: "LOADING" },
  );
  assert.deepEqual(
    projectAgentToolkitManagementState({
      loading: false,
      error: "Agent administrator access required",
    }),
    { type: "ERROR", message: "Agent administrator access required" },
  );
});

void test("projects shared candidates into stable select options", () => {
  assert.deepEqual(
    projectAgentToolkitManagementState({
      loading: false,
      error: null,
      data: {
        items: [],
        available_shared: [
          { id: "toolkit-1", name: "Workspace GitHub", toolkit_type: "github" },
        ],
      },
      toolkitDefinitions: [
        { slug: "github", name: "GitHub" },
        { slug: "shell", name: "Shell" },
      ],
    }),
    {
      type: "READY",
      items: [],
      toolkitTypes: [{ value: "github", label: "GitHub" }],
      availableShared: [
        {
          value: "toolkit-1",
          label: "Workspace GitHub (github)",
          toolkitType: "github",
        },
      ],
    },
  );
});
