import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createContext, Script } from "node:vm";
import { TRPCError } from "@trpc/server";
import ts from "typescript";
import { object } from "../../shared/testing/hook-test-harness.ts";
import * as targets from "../../shared/toolkits/mcp-callback-target.ts";

type Query = Record<string, string | string[] | null>;
function callback(): {
  calls: Array<{ route: string; input: unknown }>;
  page: (params: Query) => Promise<Record<string, unknown>>;
} {
  const calls: Array<{ route: string; input: unknown }> = [];
  const operation =
    (route: string): ((input: unknown) => Promise<void>) =>
    (input: unknown): Promise<void> => {
      calls.push({ route, input });
      return Promise.resolve();
    };
  const exports: Record<string, unknown> = {};
  const modules: Record<string, unknown> = {
    "@trpc/server": { TRPCError },
    react: {
      cache: (handler: (...args: unknown[]) => Promise<unknown>): unknown => {
        const results = new Map<string, Promise<unknown>>();
        return (...args: unknown[]): Promise<unknown> => {
          const key = JSON.stringify(args);
          const prior = results.get(key);
          if (prior != null) {
            return prior;
          }
          const result = handler(...args);
          results.set(key, result);
          return result;
        };
      },
    },
    "react/jsx-runtime": {
      jsx: (_view: unknown, props: unknown): unknown => props,
    },
    "@/features/toolkits/OAuthMcpCallbackPage": {
      OAuthMcpCallbackPage: (): void => {},
    },
    "@/shared/toolkits/mcp-callback-target": targets,
    "@/trpc/server": {
      trpc: {
        toolkit: {
          oauthExchange: operation("shared"),
          agentOauthExchange: operation("agent"),
        },
        personalToolkit: { exchangeOauth: operation("personal") },
      },
    },
  };
  const source = readFileSync(
    new URL("../../app/(app)/oauth/mcp/callback/page.tsx", import.meta.url),
    "utf8",
  );
  new Script(
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
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
  return {
    calls,
    page: async (params) => {
      const handler = exports.default;
      assert.equal(typeof handler, "function");
      if (typeof handler !== "function") {
        throw new Error("Missing callback Page");
      }
      return object(
        await Reflect.apply(handler, null, [
          { searchParams: Promise.resolve(params) },
        ]),
      );
    },
  };
}
for (const [route, params] of [
  ["personal", { personal_toolkit_config_id: "personal", handle: "workspace" }],
  ["shared", { handle: "team", toolkit_config_id: "shared" }],
  [
    "agent",
    { handle: "team", agent_id: "agent", toolkit_config_id: "agent-only" },
  ],
] satisfies Array<[string, Query]>) {
  void test(`Actual MCP callback exchanges the exact ${route} target once`, async () => {
    const fixture = callback();
    const query = { ...params, code: "fixture-code", state: "opaque-state" };
    const result = await fixture.page(query);
    assert.equal(result.success, true);
    await fixture.page(query);
    assert.equal(fixture.calls.length, 1);
    const [call] = fixture.calls;
    assert.ok(call);
    assert.equal(call.route, route);
    const input = object(call.input);
    if (route === "personal") {
      assert.equal(input.toolkitId, "personal");
      assert.equal(input.handle, "workspace");
      assert.equal(Object.hasOwn(input, "agentId"), false);
      assert.equal(
        result.returnHref,
        "/w/workspace/personal-tools/personal/edit",
      );
    }
  });
}
void test("Mixed personal/workload and malformed MCP targets never exchange", async () => {
  const fixture = callback();
  const invalid: Query[] = [
    { personal_toolkit_config_id: "personal" },
    { personal_toolkit_config_id: "personal", agent_id: "agent" },
    { personal_toolkit_config_id: "personal", toolkit_config_id: "shared" },
    { personal_toolkit_config_id: ["one", "two"] },
    { personal_toolkit_config_id: "" },
    { toolkit_config_id: "shared" },
  ];
  for (const params of invalid) {
    const result = await fixture.page({
      ...params,
      code: "fixture-code",
      state: "opaque-state",
    });
    assert.equal(result.success, false);
  }
  const denied = await fixture.page({
    personal_toolkit_config_id: "personal",
    error: "access_denied",
  });
  assert.equal(denied.success, false);
  assert.equal(fixture.calls.length, 0);
});
