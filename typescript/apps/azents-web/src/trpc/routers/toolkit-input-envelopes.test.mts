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
import * as personalToolkitInputs from "../../shared/toolkits/personal-toolkit-inputs.ts";
import * as toolkitOwnerScope from "../../shared/toolkits/toolkit-owner-scope.ts";

interface OperationFixture {
  name: string;
  input: Record<string, unknown>;
}
const personalSaved = { handle: "workspace", toolkitId: "personal" };
const accessDelta = {
  expected_mode: "all",
  mode: null,
  allow_agent_ids: [],
  restrict_agent_ids: ["agent"],
};
const personalFixtures: OperationFixture[] = [
  { name: "list", input: { handle: "workspace" } },
  { name: "eligibleAgents", input: { handle: "workspace" } },
  { name: "get", input: personalSaved },
  {
    name: "create",
    input: { handle: "workspace", toolkitType: "mcp", config: {} },
  },
  { name: "update", input: personalSaved },
  { name: "remove", input: personalSaved },
  { name: "accessForAgent", input: { handle: "workspace", agentId: "agent" } },
  { name: "saveAccess", input: { ...personalSaved, ...accessDelta } },
  {
    name: "saveAccessForAgent",
    input: {
      handle: "workspace",
      agentId: "agent",
      mutations: [{ toolkit_id: "personal", ...accessDelta }],
    },
  },
  {
    name: "testConnection",
    input: {
      handle: "workspace",
      toolkitType: "mcp",
      toolkitConfigId: null,
      config: {},
      credentials: null,
    },
  },
  { name: "testSavedConnection", input: personalSaved },
  { name: "connectOauth", input: personalSaved },
  {
    name: "exchangeOauth",
    input: { ...personalSaved, code: "fixture", state: "opaque" },
  },
  { name: "disconnectOauth", input: personalSaved },
];
const scope = { handle: "team" };
const agentScope = { ...scope, agentId: "agent" };
const saved = { ...scope, toolkitId: "saved" };
const configured = { ...scope, toolkitConfigId: "saved" };
const attempt = { ...scope, attemptId: "attempt" };
const exchange = { ...configured, code: "synthetic", state: "opaque" };
const desired = {
  services: ["calendar"],
  oauth_request_scopes: [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events.readonly",
  ],
  timeout: 30,
};
const reconnectSettings = { ...desired };
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
const githubUserFixtures: OperationFixture[] = [
  { name: "availability", input: scope },
  { name: "connect", input: saved },
  { name: "exchange", input: { ...saved, code: "fixture", state: "opaque" } },
  { name: "review", input: { ...saved, attemptId: "attempt" } },
  { name: "confirm", input: { ...saved, attemptId: "attempt" } },
  { name: "cancel", input: { ...saved, attemptId: "attempt" } },
  { name: "disconnect", input: saved },
  { name: "status", input: saved },
  { name: "access", input: { ...saved, cursor: null } },
];
const githubCreationFixtures: OperationFixture[] = [
  { name: "app", input: attempt },
  {
    name: "connect",
    input: {
      ...scope,
      toolkitType: "github",
      description: null,
      prompt: null,
      config: { github_auth_type: "github_app_platform_user" },
      enabled: true,
      alwaysExposeTools: false,
    },
  },
  { name: "exchange", input: { ...scope, code: "fixture", state: "opaque" } },
  { name: "review", input: attempt },
  {
    name: "confirm",
    input: {
      ...attempt,
      settings: {
        name: null,
        slug: null,
        description: null,
        prompt: null,
        enabled: true,
        always_expose_tools: false,
        toolsets: ["repos"],
        timeout: 30,
        inject_runtime_environment: false,
        runtime_risk_acknowledged: false,
      },
    },
  },
  { name: "cancel", input: attempt },
];
const githubSetupFixtures: OperationFixture[] = [
  { name: "app", input: scope },
  {
    name: "verify",
    input: {
      ...scope,
      verification: {
        github_auth_type: "pat",
        token: "fixture-token",
        transport: { toolsets: ["repos"], timeout: 30 },
      },
    },
  },
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
  { name: "services", input: { ...saved, services: [], expectedRevision: 1 } },
  {
    name: "pickerToken",
    input: { ...saved, expectedRevision: 1, connectionId: "connection" },
  },
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
  resHeaders: Headers;
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
        sdk[name] = (
          input: unknown,
        ): Promise<{ data: null | { items: [] } }> => {
          sdkCalls.push({ name, input });
          return Promise.resolve({
            data: [
              "agentV1ListAgents",
              "personalToolkitV1ListPersonalToolkitAgents",
            ].includes(name)
              ? { items: [] }
              : null,
          });
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
    "@/shared/toolkits/personal-toolkit-inputs": personalToolkitInputs,
    "@/shared/toolkits/toolkit-owner-scope": toolkitOwnerScope,
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
  const resHeaders = new Headers();
  const caller = invoke(record(actualRouter).createCaller, actualRouter, {
    apiClient: {},
    resHeaders,
  });
  assert.ok(
    caller != null &&
      (typeof caller === "object" || typeof caller === "function"),
  );
  return {
    procedures: record(record(record(actualRouter)._def).procedures),
    sdkCalls,
    resHeaders,
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
function declaredInputKeys(parser: unknown): string[] {
  const definition = record(record(parser).def);
  if (definition.type === "object") {
    return Object.keys(record(definition.shape));
  }
  assert.equal(definition.type, "union");
  assert.ok(Array.isArray(definition.options));
  return definition.options.flatMap(declaredInputKeys);
}
for (const [file, exportName, fixtures] of [
  ["./google.ts", "googleRouter", googleFixtures],
  ["./toolkit.ts", "toolkitRouter", toolkitFixtures],
  ["./personal-toolkit.ts", "personalToolkitRouter", personalFixtures],
  ["./github-user.ts", "githubUserRouter", githubUserFixtures],
  [
    "./github-user-creation.ts",
    "githubUserCreationRouter",
    githubCreationFixtures,
  ],
  ["./github-setup.ts", "githubSetupRouter", githubSetupFixtures],
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
      assert.equal(
        fixture.sdkCalls.length,
        count + (operation.name === "eligibleAgents" ? 2 : 1),
      );
    });
  }
  void test(`${exportName} accepts declared Agent ownership without nullable/unknown widening`, async () => {
    for (const operation of fixtures) {
      const procedure = fixture.procedures[operation.name];
      const candidate = { ...operation.input, agentId: "agent" };
      const keys = declaredInputKeys(inputParser(procedure));
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
void test("Google Picker relay retains non-cacheable browser response headers", async () => {
  const fixture = routerFixture("./google.ts", "googleRouter");
  await fixture.call("pickerToken", {
    ...saved,
    expectedRevision: 1,
    connectionId: "connection",
  });
  assert.equal(fixture.resHeaders.get("Cache-Control"), "no-store");
  assert.equal(fixture.resHeaders.get("Pragma"), "no-cache");
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
      access_token: "injected-credential",
    }).success,
    false,
  );
});

void test("Common Provider connection tests retain config and credentials for personal ownership", async () => {
  const fixture = routerFixture("./toolkit.ts", "toolkitRouter");
  for (const toolkitType of [
    "mcp",
    "notion",
    "sentry",
    "github",
    "google",
    "aws",
    "gcp",
    "kubernetes",
    "google_analytics",
    "brave_search",
  ]) {
    await fixture.call("testConnection", {
      owner: "user",
      handle: "workspace",
      toolkitType,
      toolkitConfigId: "personal",
      config: opaque,
      credentials: opaque,
    });
    const sdk = record(fixture.sdkCalls.at(-1));
    assert.equal(sdk.name, "personalToolkitOauthV1TestPersonalConnection");
    const input = record(sdk.input);
    const body = record(input.body);
    assert.equal(body.toolkit_type, toolkitType);
    assert.equal(body.toolkit_config_id, "personal");
    assert.deepEqual(body.config, opaque);
    assert.deepEqual(body.credentials, opaque);
    assert.equal(record(input.path).handle, "workspace");
  }
  const count = fixture.sdkCalls.length;
  for (const injected of [
    { handle: "" },
    { agentId: "agent" },
    { userId: "foreign" },
  ]) {
    await assert.rejects(() =>
      fixture.call("testConnection", {
        owner: "user",
        handle: "workspace",
        toolkitType: "mcp",
        toolkitConfigId: null,
        config: {},
        credentials: null,
        ...injected,
      }),
    );
  }
  assert.equal(fixture.sdkCalls.length, count);
});

for (const [file, routerName, fixtures, prefix] of [
  [
    "./github-user.ts",
    "githubUserRouter",
    githubUserFixtures,
    "personalGithubToolkitV1PersonalGithub",
  ],
  [
    "./github-user-creation.ts",
    "githubUserCreationRouter",
    githubCreationFixtures,
    "personalGithubToolkitV1PersonalGithubCreation",
  ],
  [
    "./github-setup.ts",
    "githubSetupRouter",
    githubSetupFixtures,
    "personalGithubToolkitV1PersonalGithubSetup",
  ],
] satisfies Array<[string, string, OperationFixture[], string]>) {
  for (const operation of fixtures) {
    void test(`${routerName}.${operation.name} preserves exact personal authentication target`, async () => {
      const fixture = routerFixture(file, routerName);
      const personal = {
        ...Object.fromEntries(
          Object.entries(operation.input).filter(
            ([key]) => key !== "handle" && key !== "agentId",
          ),
        ),
        owner: "user",
        handle: "workspace",
      };
      await fixture.call(operation.name, personal);
      const call = record(fixture.sdkCalls[0]);
      assert.equal(
        call.name,
        `${prefix}${operation.name[0]?.toUpperCase()}${operation.name.slice(1)}`,
      );
      const input = record(call.input);
      if (input.path != null) {
        assert.equal(record(input.path).handle, "workspace");
        assert.equal(Object.hasOwn(record(input.path), "agent_id"), false);
      }
      for (const extra of [
        { handle: "" },
        { agentId: "agent" },
        { userId: "foreign" },
      ]) {
        await assert.rejects(() =>
          fixture.call(operation.name, { ...personal, ...extra }),
        );
        assert.equal(fixture.sdkCalls.length, 1);
      }
    });
  }
}

void test("Personal GitHub Platform setup routes and OAuth inventory use User-global SDK operations", async () => {
  const fixture = routerFixture("./toolkit.ts", "toolkitRouter");
  for (const [operation, suffix, extra] of [
    ["getGithubInstallUrl", "InstallUrl", {}],
    ["getGithubOauthUrl", "InstallationOauthUrl", {}],
    [
      "getGithubInstallations",
      "SyncInstallations",
      { code: "fixture", state: "opaque" },
    ],
  ] satisfies Array<[string, string, Record<string, unknown>]>) {
    await fixture.call(operation, {
      owner: "user",
      handle: "workspace",
      ...extra,
    });
    const call = record(fixture.sdkCalls.at(-1));
    assert.equal(call.name, `personalGithubToolkitV1PersonalGithub${suffix}`);
    assert.equal(record(record(call.input).path).handle, "workspace");
  }
});

for (const operation of googleFixtures) {
  void test(`Google ${operation.name} uses only the personal SDK branch for User ownership`, async () => {
    const fixture = routerFixture("./google.ts", "googleRouter");
    const personal = {
      ...Object.fromEntries(
        Object.entries(operation.input).filter(
          ([key]) => key !== "handle" && key !== "agentId",
        ),
      ),
      owner: "user",
      handle: "workspace",
    };
    await fixture.call(operation.name, personal);
    assert.equal(fixture.sdkCalls.length, 1);
    const sdkCall = record(fixture.sdkCalls[0]);
    assert.equal(
      sdkCall.name,
      `personalGoogleToolkitV1PersonalGoogle${operation.name[0]?.toUpperCase()}${operation.name.slice(1)}`,
    );
    const sdkInput = record(sdkCall.input);
    const path = sdkInput.path == null ? {} : record(sdkInput.path);
    assert.equal(path.handle, "workspace");
    assert.equal(Object.hasOwn(path, "agent_id"), false);
    for (const injected of [
      { handle: "" },
      { agentId: "agent" },
      { userId: "foreign" },
      { workspaceId: "workload" },
    ]) {
      await assert.rejects(
        () => fixture.call(operation.name, { ...personal, ...injected }),
        (error: unknown) =>
          error instanceof TRPCError && error.code === "BAD_REQUEST",
      );
      assert.equal(fixture.sdkCalls.length, 1);
    }
  });
}
