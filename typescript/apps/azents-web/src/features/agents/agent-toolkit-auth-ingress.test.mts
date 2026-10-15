import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createContext, Script } from "node:vm";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";
import {
  BrowserStorageFixture,
  HookHarness,
  invoke,
  noMutation,
  object,
} from "../../shared/testing/hook-test-harness.ts";
import * as githubCreation from "../../shared/toolkits/github-user-creation-state.ts";
import * as githubOAuth from "../../shared/toolkits/github-user-oauth-state.ts";
import * as googleResume from "../../shared/toolkits/google-resume.ts";
import * as providerConfigViews from "../../shared/toolkits/provider-config-views.ts";
import * as formLifecycle from "../../shared/toolkits/toolkit-form-lifecycle.ts";
import * as managementState from "./agentToolkitManagementState.ts";
import type { AgentToolkitManagementItemResponse } from "@azents/public-client";

function query(data: unknown): Record<string, unknown> {
  return {
    data,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
  };
}

function managementView(): unknown {
  const path = new URL(
    "./components/ManagedAgentToolkitSection.tsx",
    import.meta.url,
  );
  const source = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const widgets = Object.fromEntries(
    [
      "Alert",
      "Badge",
      "Button",
      "Card",
      "Group",
      "Loader",
      "Modal",
      "SimpleGrid",
      "Stack",
      "Tabs",
      "Text",
      "Title",
    ].map((name) => [name, `fixture-${name}`]),
  );
  const modules: Record<string, unknown> = {
    "react/jsx-runtime": jsxRuntime,
    "@mantine/core": {
      ...widgets,
      rem: (value: number): string => `${value / 16}rem`,
    },
    "@tabler/icons-react": {
      IconArrowLeft: "fixture-arrow",
      IconLock: "fixture-lock",
      IconPlus: "fixture-plus",
    },
    "next-intl": {
      useTranslations:
        () =>
        (key: string): string =>
          key,
    },
    "next/link": { default: "fixture-link" },
    "@/shared/toolkits/components/ToolkitTypeIcon": {
      ToolkitTypeIcon: "fixture-icon",
    },
    "@/shared/toolkits/GitHubUserAuthorizationContainer": {
      GitHubUserAuthorizationContainer: "fixture-user",
    },
    "@/shared/toolkits/provider-config-views": providerConfigViews,
    "@/shared/toolkits/toolkit-detail-projection": {
      projectToolkitDetails: (): [] => [],
    },
    "@/shared/toolkits/toolkit-form-lifecycle": formLifecycle,
    "@/shared/toolkits/ToolkitFormContainer": {
      ToolkitFormContainer: "fixture-form",
    },
    "../agentToolkitManagementState": managementState,
  };
  const exports: Record<string, unknown> = {};
  new Script(source, { filename: path.pathname }).runInContext(
    createContext({
      exports,
      module: { exports },
      require: (name: string): unknown => {
        assert.ok(
          Object.hasOwn(modules, name),
          `Missing explicit view test boundary: ${name}`,
        );
        return modules[name];
      },
    }),
  );
  return exports.ManagedAgentToolkitSectionView;
}

function cardProps(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) {
    return value.flatMap(cardProps);
  }
  if (value == null || typeof value !== "object") {
    return [];
  }
  const data = object(value);
  if (
    typeof data.type === "function" &&
    data.type.name === "ManagedToolkitCard"
  ) {
    return [object(data.props)];
  }
  return Object.values(data).flatMap(cardProps);
}

void test("actual Agent authorization keeps exact GitHub user modes and shared ownership authority", () => {
  const view = managementView();
  for (const mode of [
    "pat",
    "github_app",
    "github_app_platform",
    "github_app_user",
    "github_app_platform_user",
    "future",
    "",
    null,
    void 0,
    false,
    1,
    [],
    { future: true },
    { toString: null },
    { toString: 1 },
    { toString: {} },
    { toString: [], valueOf: null },
  ]) {
    for (const ownership_scope of ["agent_only", "workspace_shared"] as const) {
      for (const role of ["owner", "member"]) {
        const item: AgentToolkitManagementItemResponse = {
          ownership_scope,
          agent_toolkit_id: "attachment",
          readiness: "authorization_required",
          toolkit: {
            id: "toolkit",
            workspace_id: "workspace",
            toolkit_type: "github",
            slug: "fixture",
            name: "Fixture",
            description: null,
            prompt: null,
            enabled: true,
            always_expose_tools: false,
            config: { github_auth_type: mode, future: { opaque: true } },
            created_at: "2026-10-15T00:00:00Z",
            updated_at: "2026-10-15T00:00:00Z",
          },
        };
        const original = JSON.stringify(item);
        const store = new BrowserStorageFixture(
          githubOAuth.GITHUB_USER_CONTEXT_KEY,
        );
        const harness = new HookHarness();
        const toolkit: Record<string, unknown> = {
          listAgentManagement: {
            useQuery: () => query({ items: [item], available_shared: [] }),
          },
          listToolkits: {
            useQuery: () =>
              query({ items: [{ slug: "github", name: "GitHub" }] }),
          },
        };
        for (const name of [
          "attachToAgent",
          "detachFromAgent",
          "updateAgentConfig",
          "removeAgentConfig",
          "connectOauth",
          "connectAgentOauth",
        ]) {
          toolkit[name] = { useMutation: noMutation };
        }
        let opened = 0;
        harness.load(
          new URL(
            "./containers/useAgentToolkitManagementContainer.ts",
            import.meta.url,
          ),
          "useAgentToolkitManagementContainer",
          {
            react: harness.react,
            "@mantine/hooks": store.mantine,
            "next-intl": {
              useTranslations:
                () =>
                (key: string): string =>
                  key,
            },
            "@/shared/toolkits/github-user-creation-state": githubCreation,
            "@/shared/toolkits/github-user-oauth-state": githubOAuth,
            "@/shared/toolkits/google-resume": googleResume,
            "@/shared/toolkits/provider-config-views": providerConfigViews,
            "@/shared/toolkits/toolkit-form-lifecycle": formLifecycle,
            "../agentToolkitManagementState": managementState,
            "@/trpc/client": {
              trpc: {
                toolkit,
                useUtils: () => ({ toolkit: {} }),
                workspaceMember: { me: { useQuery: () => query({ role }) } },
              },
            },
          },
          {
            location: { origin: "https://app.example.invalid" },
            open: () => {
              opened += 1;
              return { closed: false };
            },
          },
        );
        const output = harness.render({ handle: "team", agentId: "agent" });
        invoke(output.onAuthorize, item);
        const expected =
          (mode === "github_app_user" || mode === "github_app_platform_user") &&
          (ownership_scope === "agent_only" || role === "owner");
        assert.equal(opened, expected ? 1 : 0);
        const editor = object(harness.render().editor);
        assert.equal(editor.type, expected ? "DETAIL" : "CLOSED");
        if (expected) {
          assert.equal(editor.toolkitConfigId, item.toolkit.id);
          const context = object(store.value);
          assert.equal(context.toolkitId, item.toolkit.id);
          assert.equal(
            context.agentId,
            ownership_scope === "agent_only" ? "agent" : void 0,
          );
          assert.equal(
            context.returnPath,
            "/w/team/agents/agent/settings/capabilities#agent-toolkits",
          );
        } else {
          assert.equal(store.writes.length, 0);
        }
        const rendered = invoke(view, {
          handle: "team",
          agentId: "agent",
          editor: { type: "DETAIL", toolkitConfigId: item.toolkit.id },
          state: {
            type: "READY",
            items: [item],
            toolkitTypes: [],
            availableShared: [],
          },
          mutationState: { type: "IDLE" },
          pending: false,
          setupPending: false,
          deleteTarget: null,
          canAuthorizeShared: role === "owner",
          githubUserView: "current-user-connection",
        });
        const cards = cardProps(rendered);
        assert.equal(cards.length, 1);
        assert.equal(
          cards[0]?.userConnectionView,
          expected ? "current-user-connection" : null,
        );
        assert.equal(JSON.stringify(item), original);
      }
    }
  }
});
