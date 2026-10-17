import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createContext, Script } from "node:vm";
import ts from "typescript";
import {
  deferred,
  HookHarness,
  invoke,
  object,
} from "../testing/hook-test-harness.ts";
import * as toolkitOwnerScope from "./toolkit-owner-scope.ts";

function commonTestHook(captured: unknown[]): unknown {
  const exports: Record<string, unknown> = {};
  const modules: Record<string, unknown> = {
    "@/trpc/client": {
      trpc: {
        toolkit: {
          testConnection: {
            useMutation: () => ({
              isPending: false,
              isSuccess: false,
              isError: false,
              mutate: (input: unknown): void => {
                captured.push(input);
              },
            }),
          },
        },
      },
    },
    "../toolkit-owner-scope": toolkitOwnerScope,
  };
  const path = new URL(
    "./containers/useProviderConnectionTest.ts",
    import.meta.url,
  );
  new Script(
    ts.transpileModule(readFileSync(path, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
  ).runInContext(
    createContext({
      exports,
      module: { exports },
      require: (name: string): unknown => {
        assert.ok(Object.hasOwn(modules, name));
        return modules[name];
      },
    }),
  );
  return exports.useProviderConnectionTest;
}
const values = {
  config: { timeout: 30 },
  credentials: null,
  hasCredentials: false,
  onConfigChange: (): void => {},
  onCredentialsChange: (): void => {},
  toolkitConfigId: "saved",
};
for (const provider of [
  "aws",
  "gcp",
  "google_analytics",
  "kubernetes",
  "notion",
  "sentry",
]) {
  void test(`Common ${provider} field test preserves explicit personal ownership`, () => {
    const captured: unknown[] = [];
    const control = object(
      invoke(
        commonTestHook(captured),
        { ...values, owner: "user", handle: "workspace" },
        provider,
      ),
    );
    invoke(control.onTestConnection);
    assert.equal(captured.length, 1);
    assert.equal(object(captured[0]).owner, "user");
    assert.equal(object(captured[0]).toolkitType, provider);
    assert.equal(object(captured[0]).handle, "workspace");
    assert.equal(Object.hasOwn(object(captured[0]), "agentId"), false);
  });
}
void test("Common field test retains existing shared and Agent ownership", () => {
  const captured: unknown[] = [];
  const hook = commonTestHook(captured);
  for (const scope of [
    { handle: "team" },
    { handle: "team", agentId: "agent" },
  ]) {
    invoke(
      object(invoke(hook, { ...values, ...scope }, "aws")).onTestConnection,
    );
    const input = object(captured.at(-1));
    assert.equal(input.handle, "team");
    assert.equal(input.agentId, scope.agentId);
    assert.equal(Object.hasOwn(input, "owner"), false);
  }
});
void test("Actual MCP field container tests personal credentials with a required Workspace handle", async () => {
  const h = new HookHarness();
  const called = deferred<void>();
  let captured: unknown = null;
  h.load(
    new URL("./containers/useMcpConfigFieldsContainer.ts", import.meta.url),
    "useMcpConfigFieldsContainer",
    {
      react: h.react,
      "next-intl": {
        useTranslations:
          () =>
          (key: string): string =>
            key,
      },
      "@/trpc/client": {
        trpc: {
          toolkit: {
            testConnection: {
              useMutation: () => ({
                mutateAsync: (input: unknown): Promise<unknown> => {
                  captured = input;
                  called.resolve();
                  return Promise.resolve({
                    success: true,
                    message: "Connected",
                    discovered_auth_url: null,
                    discovered_token_url: null,
                    supports_dcr: null,
                  });
                },
              }),
            },
          },
        },
      },
    },
    {},
  );
  const output = object(
    h.render({ ...values, owner: "user", handle: "workspace" }),
  );
  invoke(output.onTestConnection);
  await called.promise;
  assert.equal(object(captured).owner, "user");
  assert.equal(object(captured).toolkitType, "mcp");
  assert.equal(object(captured).handle, "workspace");
});
