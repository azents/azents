import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createContext, Script } from "node:vm";
import { initTRPC, TRPCError } from "@trpc/server";
import ts from "typescript";
import { z } from "zod/v4";
import { normalizeCredentialEdits } from "../../shared/lib/redacted-credentials.ts";
import { normalizeExplicitToolkitSlug } from "../../shared/lib/toolkit-identifiers.ts";
import * as googleSchemas from "../../shared/toolkits/google-schemas.ts";

interface OperationFixture {
  name: string;
  input: Record<string, unknown>;
}
const scope = { handle: "team" };
const agentScope = { ...scope, agentId: "agent" };
const saved = { ...scope, toolkitId: "saved" };
const configured = { ...scope, toolkitConfigId: "saved" };
const attempt = { ...scope, attemptId: "attempt" };
const exchange = { ...configured, code: "synthetic", state: "opaque" };
const desired = { tasks: ["calendar_read"], timeout: 30 };
const reconnectSettings = { ...desired, security_risk_acknowledged: true };
const settings = {
  ...reconnectSettings,
  name: null,
  slug: null,
  description: null,
  prompt: null,
  enabled: true,
  always_expose_tools: false,
};
const opaque = { extension: { nullable: null, nested: ["value", 4, true] } };
const connection = {
  ...scope,
  toolkitConfigId: null,
  config: opaque,
  credentials: null,
};
const toolkitFixtures: OperationFixture[] = [
  { name: "listConfigs", input: scope },
  { name: "listAvailableConfigs", input: scope },
  { name: "getConfig", input: saved },
  {
    name: "createConfig",
    input: { ...scope, toolkitType: "mcp", config: opaque },
  },
  { name: "updateConfig", input: saved },
  { name: "removeConfig", input: saved },
  { name: "listAgentToolkits", input: agentScope },
  { name: "attachToAgent", input: { ...agentScope, toolkitId: "saved" } },
  {
    name: "detachFromAgent",
    input: { ...agentScope, agentToolkitId: "attached" },
  },
  { name: "getGithubInstallUrl", input: scope },
  { name: "getGithubOauthUrl", input: scope },
  {
    name: "getGithubInstallations",
    input: { ...scope, code: "synthetic", state: "opaque" },
  },
  { name: "connectOauth", input: configured },
  { name: "oauthExchange", input: exchange },
  { name: "disconnectOauth", input: configured },
  { name: "testConnection", input: connection },
  { name: "listAgentManagement", input: agentScope },
  {
    name: "createAgentConfig",
    input: {
      ...agentScope,
      toolkitType: "mcp",
      config: opaque,
      enabled: true,
      alwaysExposeTools: false,
    },
  },
  {
    name: "getAgentConfig",
    input: { ...agentScope, toolkitConfigId: "saved" },
  },
  {
    name: "updateAgentConfig",
    input: { ...agentScope, toolkitConfigId: "saved" },
  },
  {
    name: "removeAgentConfig",
    input: { ...agentScope, toolkitConfigId: "saved" },
  },
  { name: "getAgentGithubInstallUrl", input: agentScope },
  { name: "getAgentGithubOauthUrl", input: agentScope },
  {
    name: "getAgentGithubInstallations",
    input: { ...agentScope, code: "synthetic", state: "opaque" },
  },
  {
    name: "connectAgentOauth",
    input: { ...agentScope, toolkitConfigId: "saved" },
  },
  { name: "agentOauthExchange", input: { ...exchange, agentId: "agent" } },
  {
    name: "disconnectAgentOauth",
    input: { ...agentScope, toolkitConfigId: "saved" },
  },
  { name: "testAgentConnection", input: { ...connection, agentId: "agent" } },
];
const googleFixtures: OperationFixture[] = [
  { name: "preparation", input: scope },
  { name: "connect", input: { ...scope, desired } },
  { name: "reconnect", input: { ...saved, desired } },
  { name: "exchange", input: { ...scope, code: "synthetic", state: "opaque" } },
  { name: "review", input: attempt },
  { name: "confirm", input: { ...attempt, settings } },
  {
    name: "reconnectConfirm",
    input: { ...attempt, settings: reconnectSettings },
  },
  { name: "cancel", input: attempt },
  { name: "outcome", input: attempt },
  { name: "status", input: saved },
  { name: "disconnect", input: saved },
];
function record(value: unknown): Record<string, unknown> {
  assert.ok(
    value != null &&
      (typeof value === "object" || typeof value === "function") &&
      !Array.isArray(value),
  );
  return Object.fromEntries(
    Object.getOwnPropertyNames(value)
      .filter((key) => key !== "caller" && key !== "arguments")
      .map((key) => [key, Reflect.get(value, key)]),
  );
}
function invoke(
  value: unknown,
  receiver: unknown,
  ...args: unknown[]
): unknown {
  assert.equal(typeof value, "function");
  if (typeof value !== "function") {
    throw new Error("Expected a declared test boundary function.");
  }
  return Reflect.apply(value, receiver, args);
}
/** Load the actual router source; only external SDK/I/O and sibling routers are substituted. */
function routerFixture(
  file: string,
  exportName: string,
): {
  procedures: Record<string, unknown>;
  sdkCalls: unknown[];
  call: (name: string, input: unknown) => Promise<unknown>;
} {
  const path = new URL(file, import.meta.url);
  const source = readFileSync(path, "utf8");
  const syntax = ts.createSourceFile(
    path.pathname,
    source,
    ts.ScriptTarget.Latest,
    true,
  );
  const sdkCalls: unknown[] = [];
  const sdk: Record<string, unknown> = {};
  for (const statement of syntax.statements) {
    if (
      ts.isImportDeclaration(statement) &&
      ts.isStringLiteral(statement.moduleSpecifier) &&
      statement.moduleSpecifier.text === "@azents/public-client"
    ) {
      const bindings = statement.importClause?.namedBindings;
      assert.ok(bindings && ts.isNamedImports(bindings));
      for (const binding of bindings.elements) {
        const name = binding.name.text;
        sdk[name] = (input: unknown): Promise<{ data: null }> => {
          sdkCalls.push({ name, input });
          return Promise.resolve({ data: null });
        };
      }
    }
  }
  const t = initTRPC.create();
  const modules: Record<string, unknown> = {
    "@azents/public-client": sdk,
    "zod/v4": { z },
    "@/shared/lib/redacted-credentials": { normalizeCredentialEdits },
    "@/shared/lib/toolkit-identifiers": { normalizeExplicitToolkitSlug },
    "@/shared/toolkits/google-schemas": googleSchemas,
    "../api-error": { mapExpectedError: (error: unknown): unknown => error },
    "../init": { publicProcedure: t.procedure, router: t.router },
    "./github-setup": { githubSetupRouter: t.router({}) },
    "./github-user": { githubUserRouter: t.router({}) },
    "./github-user-creation": { githubUserCreationRouter: t.router({}) },
    "./google": { googleRouter: t.router({}) },
  };
  const exports: Record<string, unknown> = {};
  const context = createContext({
    exports,
    module: { exports },
    require: (name: string): unknown => {
      assert.ok(
        Object.hasOwn(modules, name),
        `Missing explicit router test boundary: ${name}`,
      );
      return modules[name];
    },
  });
  new Script(
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
    { filename: path.pathname },
  ).runInContext(context);
  const actualRouter = exports[exportName];
  const caller = invoke(record(actualRouter).createCaller, actualRouter, {
    apiClient: {},
  });
  assert.ok(
    caller != null &&
      (typeof caller === "object" || typeof caller === "function"),
  );
  return {
    procedures: record(record(record(actualRouter)._def).procedures),
    sdkCalls,
    call: async (name, input) =>
      await invoke(Reflect.get(caller, name), null, input),
  };
}
function inputParser(procedure: unknown): unknown {
  const definition = record(record(procedure)._def);
  assert.ok(Array.isArray(definition.inputs));
  assert.equal(definition.inputs.length, 1);
  return definition.inputs[0];
}
async function parse(procedure: unknown, input: unknown): Promise<unknown> {
  const parser = inputParser(procedure);
  return await invoke(record(parser).parseAsync, parser, input);
}
for (const [file, exportName, fixtures] of [
  ["./google.ts", "googleRouter", googleFixtures],
  ["./toolkit.ts", "toolkitRouter", toolkitFixtures],
] satisfies Array<[string, string, OperationFixture[]]>) {
  const fixture = routerFixture(file, exportName);
  void test(`${exportName} inventory covers every input-bearing operation`, () => {
    const actual = Object.entries(fixture.procedures)
      .filter(([, procedure]) => {
        const inputs = record(record(procedure)._def).inputs;
        return Array.isArray(inputs) && inputs.length > 0;
      })
      .map(([name]) => name)
      .sort();
    assert.deepEqual(actual, fixtures.map((item) => item.name).sort());
  });
  for (const operation of fixtures) {
    void test(`${exportName}.${operation.name} rejects unknown envelope fields before SDK mutation`, async () => {
      const procedure = fixture.procedures[operation.name];
      assert.ok(procedure);
      await assert.doesNotReject(() => parse(procedure, operation.input));
      const extra = {
        ...operation.input,
        unintended_identity: "ignored-before-correction",
      };
      const count = fixture.sdkCalls.length;
      await assert.rejects(
        () => fixture.call(operation.name, extra),
        (error: unknown) =>
          error instanceof TRPCError && error.code === "BAD_REQUEST",
      );
      assert.equal(fixture.sdkCalls.length, count);
      await assert.rejects(() => parse(procedure, extra));
      await fixture.call(operation.name, operation.input);
      assert.equal(fixture.sdkCalls.length, count + 1);
    });
  }
  void test(`${exportName} accepts declared Agent ownership without nullable/unknown widening`, async () => {
    for (const operation of fixtures) {
      const procedure = fixture.procedures[operation.name];
      const candidate = { ...operation.input, agentId: "agent" };
      const keys = Object.keys(
        record(record(record(inputParser(procedure)).def).shape),
      );
      if (keys.includes("agentId")) {
        await assert.doesNotReject(() => parse(procedure, candidate));
        await assert.rejects(() =>
          parse(procedure, { ...candidate, agentId: null }),
        );
      }
    }
  });
}
void test("Toolkit envelopes preserve opaque records, defaults and nullable patch values", async () => {
  const fixture = routerFixture("./toolkit.ts", "toolkitRouter");
  for (const name of [
    "createConfig",
    "createAgentConfig",
    "updateConfig",
    "updateAgentConfig",
    "testConnection",
    "testAgentConnection",
  ]) {
    const item = toolkitFixtures.find((operation) => operation.name === name);
    assert.ok(item);
    const input = { ...item.input, config: opaque, credentials: opaque };
    const parsed = record(await parse(fixture.procedures[name], input));
    assert.deepEqual(parsed.config, opaque);
    assert.deepEqual(parsed.credentials, opaque);
  }
  assert.equal(
    record(await parse(fixture.procedures.testConnection, connection))
      .toolkitType,
    "mcp",
  );
  for (const name of ["updateConfig", "updateAgentConfig"]) {
    const item = toolkitFixtures.find((operation) => operation.name === name);
    assert.ok(item);
    const omitted = record(await parse(fixture.procedures[name], item.input));
    assert.equal(Object.hasOwn(omitted, "description"), false);
    const explicit = record(
      await parse(fixture.procedures[name], {
        ...item.input,
        description: null,
        prompt: null,
      }),
    );
    assert.equal(explicit.description, null);
    assert.equal(explicit.prompt, null);
  }
  const input = { ...agentScope, toolkitConfigId: "saved", credentials: null };
  assert.equal(
    record(await parse(fixture.procedures.updateAgentConfig, input))
      .credentials,
    null,
  );
  await assert.rejects(() =>
    parse(fixture.procedures.updateConfig, { ...saved, credentials: null }),
  );
  const noInput = record(record(fixture.procedures.listToolkits)._def).inputs;
  assert.ok(Array.isArray(noInput));
  assert.equal(noInput.length, 0);
});
void test("Google nested schemas retain required nullable settings and reject nested protocol extras", () => {
  assert.ok(
    googleSchemas.googleFinalSettingsSchema.safeParse(settings).success,
  );
  assert.equal(
    googleSchemas.googleFinalSettingsSchema.safeParse(
      Object.fromEntries(
        Object.entries(settings).filter(([key]) => key !== "prompt"),
      ),
    ).success,
    false,
  );
  assert.equal(
    googleSchemas.googleDesiredSchema.safeParse({ ...desired, unknown: true })
      .success,
    false,
  );
  assert.equal(
    googleSchemas.googleReconnectSettingsSchema.safeParse({
      ...reconnectSettings,
      security_risk_acknowledged: "true",
    }).success,
    false,
  );
});
