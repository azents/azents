import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createContext, Script } from "node:vm";
import * as trpcServer from "@trpc/server";
import superjson from "superjson";
import ts from "typescript";
import { z } from "zod/v4";

interface SdkCall {
  name: string;
  request: unknown;
}
interface LoadedProtocol {
  exports: Record<string, unknown>;
  calls: SdkCall[];
  cookieWrites: unknown[];
}
function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Expected an explicit test-boundary object.");
  }
  return Object.fromEntries(Object.entries(value));
}
function property(value: unknown, key: string): unknown {
  if (
    value === null ||
    (typeof value !== "object" && typeof value !== "function")
  ) {
    throw new Error("Expected a test-boundary property owner.");
  }
  const result: unknown = Reflect.get(value, key);
  return result;
}
function invoke(value: unknown, ...args: unknown[]): unknown {
  if (typeof value !== "function") {
    throw new Error("Expected an explicit test-boundary function.");
  }
  const result: unknown = Reflect.apply(value, null, args);
  return result;
}
function loadProtocol(path: URL): LoadedProtocol {
  const calls: SdkCall[] = [];
  const cookieWrites: unknown[] = [];
  const sdkData = {
    items: [],
    total: 0,
    token: { email: "admin@example.test" },
    plaintext_token: "synthetic-signup-token",
    access_token: "synthetic-access-token",
    refresh_token: "synthetic-refresh-token",
    expires_in: 300,
    user_id: "admin",
  };
  const config = {
    getServerConfig: () => ({
      nodeEnv: "test",
      publicWebUrl: "https://app.example.test",
    }),
  };
  const cookies = {
    setAdminAuthCookies: (_headers: unknown, value: unknown): void => {
      cookieWrites.push(value);
    },
    clearAdminAuthCookies: (): void => {},
  };
  const clients = {
    createAdminApiClient: () => ({ name: "admin" }),
    createBootstrapAdminApiClient: () => ({ name: "bootstrap" }),
    createAuthenticatedPublicApiClient: () => ({ name: "authenticated" }),
    createPublicApiClient: () => ({ name: "public" }),
  };
  const readModule = (modulePath: URL): Record<string, unknown> => {
    const source = readFileSync(modulePath, "utf8");
    const sourceFile = ts.createSourceFile(
      modulePath.pathname,
      source,
      ts.ScriptTarget.Latest,
      true,
    );
    const sdk: Record<string, unknown> = {};
    for (const statement of sourceFile.statements) {
      if (
        !ts.isImportDeclaration(statement) ||
        !ts.isStringLiteral(statement.moduleSpecifier) ||
        !["@azents/admin-client", "@azents/public-client"].includes(
          statement.moduleSpecifier.text,
        ) ||
        statement.importClause?.isTypeOnly ||
        statement.importClause?.namedBindings == null ||
        !ts.isNamedImports(statement.importClause.namedBindings)
      ) {
        continue;
      }
      for (const item of statement.importClause.namedBindings.elements) {
        if (item.isTypeOnly) {
          continue;
        }
        const name = item.propertyName?.text ?? item.name.text;
        sdk[name] = (request: unknown): Promise<unknown> => {
          calls.push({ name, request });
          return Promise.resolve({ data: sdkData });
        };
      }
    }
    const modules: Record<string, unknown> = {
      "@azents/admin-client": sdk,
      "@azents/public-client": sdk,
      "@trpc/server": trpcServer,
      superjson: { default: superjson },
      "zod/v4": { z },
      "@/config/server": config,
      "@/shared/lib/api-clients": clients,
      "@/shared/lib/auth-cookies": cookies,
      "@/shared/lib/same-origin": {
        hasExpectedOrigin: (request: Request): boolean =>
          request.headers.get("Origin") === "https://admin.example.test",
      },
      "@/trpc/context": {
        createContext: (): Promise<unknown> =>
          Promise.resolve({ authenticated: false }),
      },
      "../api-error": {
        mapExpectedError: (error: unknown): unknown => error,
        withApiErrorInterceptor: (client: unknown): unknown => client,
      },
    };
    const exports: Record<string, unknown> = {};
    const cjsModule = { exports };
    const sandbox = createContext({
      module: cjsModule,
      exports,
      require: (name: string): unknown => {
        if (name === "../init") {
          return readModule(new URL("../init.ts", modulePath));
        }
        if (
          name === "./runtimeProviderSchemas" ||
          name === "./historical-memory-execution-input"
        ) {
          return readModule(new URL(`${name}.ts`, modulePath));
        }
        if (!Object.hasOwn(modules, name)) {
          throw new Error(`Missing explicit protocol test boundary: ${name}`);
        }
        return modules[name];
      },
      Request,
      Response,
      Headers,
      Promise,
      console,
    });
    const transformed = ts.transpileModule(source, {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        esModuleInterop: true,
      },
    }).outputText;
    new Script(transformed, { filename: modulePath.pathname }).runInContext(
      sandbox,
    );
    return cjsModule.exports;
  };
  return { exports: readModule(path), calls, cookieWrites };
}
interface OperationCase {
  module: string;
  operation: string;
  input: Record<string, unknown>;
}
const profile = {
  profile_kind: "docker_container",
  contract_family: "docker.container-profile",
  schema_version: 2,
  runner_resources: {
    cpu_reservation_millicores: null,
    cpu_limit_millicores: null,
    memory_reservation_bytes: null,
    memory_limit_bytes: null,
  },
  network_name: null,
};
const profileInput = {
  providerId: "provider",
  displayName: "Profile",
  description: "",
  lifecycle: "active",
  terminalEnabled: true,
  spec: profile,
};
const operations: OperationCase[] = [
  {
    module: "bootstrap",
    operation: "firstAdmin",
    input: {
      setupToken: "setup",
      email: "admin@example.test",
      password: "password",
    },
  },
  {
    module: "debug",
    operation: "fireLog",
    input: { level: "warning", message: "Message" },
  },
  {
    module: "debug",
    operation: "fireException",
    input: { message: "Message" },
  },
  {
    module: "signupToken",
    operation: "create",
    input: { email: "admin@example.test" },
  },
  { module: "signupToken", operation: "revoke", input: { tokenId: "token" } },
  { module: "user", operation: "get", input: { id: "user" } },
  { module: "user", operation: "delete", input: { id: "user" } },
  { module: "userEmail", operation: "listByUser", input: { user_id: "user" } },
  {
    module: "userEmail",
    operation: "create",
    input: { user_id: "user", email: "new@example.test" },
  },
  { module: "userEmail", operation: "delete", input: { email_id: "email" } },
  { module: "verification", operation: "get", input: { id: "verification" } },
  { module: "workspace", operation: "get", input: { handle: "workspace" } },
  {
    module: "workspace",
    operation: "create",
    input: { name: "Workspace", handle: "workspace" },
  },
  {
    module: "workspace",
    operation: "update",
    input: { handle: "workspace", name: "Updated", new_handle: "updated" },
  },
  {
    module: "workspaceMember",
    operation: "listByWorkspace",
    input: { workspace_handle: "workspace" },
  },
  { module: "workspaceMember", operation: "get", input: { id: "member" } },
  {
    module: "workspaceMember",
    operation: "create",
    input: {
      workspace_handle: "workspace",
      user_id: "user",
      name: "Member",
      role: "member",
    },
  },
  {
    module: "workspaceMember",
    operation: "update",
    input: { workspace_user_id: "member" },
  },
  {
    module: "workspaceMember",
    operation: "updateRole",
    input: { workspace_user_id: "member", role: "manager" },
  },
  {
    module: "workspaceMember",
    operation: "transferOwnership",
    input: {
      workspace_handle: "workspace",
      new_owner_workspace_user_id: "member",
    },
  },
  { module: "workspaceMember", operation: "delete", input: { id: "member" } },
  {
    module: "systemSettings",
    operation: "patchExternalChannelFiles",
    input: {
      expectedVersion: 0,
      outboundMaxFileBytes: 1,
      outboundMaxActionBytes: 2,
    },
  },
  {
    module: "systemSettings",
    operation: "getExternalAccountOAuth",
    input: { provider: "slack" },
  },
  {
    module: "systemSettings",
    operation: "patchExternalAccountOAuth",
    input: { provider: "discord", expectedVersion: 0, applicationId: null },
  },
  {
    module: "systemSettings",
    operation: "checkExternalAccountOAuthHealth",
    input: { provider: "discord" },
  },
  {
    module: "systemSettings",
    operation: "patchPlatformGitHubApp",
    input: { expectedVersion: 0, appId: null },
  },
  {
    module: "systemSettings",
    operation: "confirmPlatformGitHubAppCandidate",
    input: {
      candidateId: "candidate",
      expectedVersion: 0,
      confirmationAction: "activate",
    },
  },
  {
    module: "systemSettings",
    operation: "cancelPlatformGitHubAppCandidate",
    input: { candidateId: "candidate" },
  },
  { module: "systemSettings", operation: "listAuditEvents", input: {} },
  {
    module: "runtimeProvider",
    operation: "getRecreation",
    input: { operationId: "operation" },
  },
  {
    module: "runtimeProvider",
    operation: "listInfrastructureProfiles",
    input: { providerId: "provider", profileKind: "docker_container" },
  },
  {
    module: "runtimeProvider",
    operation: "getInfrastructureProfileDeletionImpact",
    input: {
      providerId: "provider",
      profileId: "profile",
      profileKind: "docker_container",
    },
  },
  {
    module: "runtimeProvider",
    operation: "deleteInfrastructureProfile",
    input: {
      providerId: "provider",
      profileId: "profile",
      profileKind: "docker_container",
      expectedVersion: 1,
    },
  },
  {
    module: "runtimeProvider",
    operation: "getWorkspaceProfileAdminDetail",
    input: { workspaceHandle: "workspace", profileId: "profile" },
  },
  {
    module: "runtimeProvider",
    operation: "createInfrastructureProfile",
    input: profileInput,
  },
  {
    module: "runtimeProvider",
    operation: "replaceInfrastructureProfile",
    input: { ...profileInput, profileId: "profile", expectedVersion: 1 },
  },
  {
    module: "runtimeProvider",
    operation: "createInfrastructureProfileRecreation",
    input: {
      providerId: "provider",
      profileId: "profile",
      profileKind: "docker_container",
      expectedVersion: 1,
    },
  },
  {
    module: "runtimeProvider",
    operation: "createProviderRecreation",
    input: { providerId: "provider", expectedVersion: 1 },
  },
  {
    module: "runtimeProvider",
    operation: "listContracts",
    input: { providerId: "provider" },
  },
  {
    module: "runtimeProvider",
    operation: "listAuthBindings",
    input: { providerId: "provider" },
  },
  {
    module: "runtimeProvider",
    operation: "listAuthBindingAuditEvents",
    input: { bindingId: "binding", offset: 0, limit: 10 },
  },
  {
    module: "runtimeProvider",
    operation: "createAuthBinding",
    input: { providerId: "provider", subject: "subject" },
  },
  {
    module: "runtimeProvider",
    operation: "rotateAuthBinding",
    input: {
      bindingId: "binding",
      expectedAdminVersion: 1,
      expiresAt: "2030-01-01T00:00:00Z",
    },
  },
  {
    module: "runtimeProvider",
    operation: "revokeAuthBinding",
    input: { bindingId: "binding", expectedAdminVersion: 1, reason: null },
  },
  {
    module: "runtimeProvider",
    operation: "get",
    input: { providerId: "provider" },
  },
  {
    module: "runtimeProvider",
    operation: "getDiagnostics",
    input: { providerId: "provider" },
  },
  {
    module: "runtimeProvider",
    operation: "updatePolicy",
    input: {
      providerId: "provider",
      enabled: true,
      lifecycleState: "active",
      availabilityMode: "selected_workspaces",
    },
  },
  {
    module: "runtimeProvider",
    operation: "replaceAvailability",
    input: { providerId: "provider", workspaceIds: [] },
  },
];
function operationCaller(
  loaded: LoadedProtocol,
  module: string,
  authenticated = true,
): unknown {
  const router = loaded.exports[`${module}Router`];
  return invoke(property(router, "createCaller"), {
    authenticated,
    accessToken: authenticated ? "synthetic-access-token" : null,
    adminApiClient: authenticated ? { name: "admin" } : null,
    responseHeaders: new Headers(),
  });
}
for (const item of operations) {
  void test(`${item.module}.${item.operation} rejects unknown envelope fields before SDK work`, async () => {
    const loaded = loadProtocol(
      new URL(`./${item.module}.ts`, import.meta.url),
    );
    const caller = operationCaller(loaded, item.module);
    await assert.rejects(
      async () =>
        await invoke(property(caller, item.operation), {
          ...item.input,
          unexpectedOperationField: "synthetic-value",
        }),
      (error: unknown) =>
        error instanceof trpcServer.TRPCError && error.code === "BAD_REQUEST",
    );
    assert.deepEqual(loaded.calls, []);
    assert.deepEqual(loaded.cookieWrites, []);
    await invoke(property(caller, item.operation), item.input);
    assert.equal(loaded.calls.length, 1);
  });
}
void test("session POST rejects an unknown field before login and cookies", async () => {
  const loaded = loadProtocol(
    new URL("../../app/api/session/route.ts", import.meta.url),
  );
  const input = { email: "admin@example.test", password: "password" };
  const send = async (body: unknown): Promise<Response> => {
    const response = await invoke(
      loaded.exports.POST,
      new Request("https://admin.example.test/api/session", {
        method: "POST",
        headers: {
          Origin: "https://admin.example.test",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      }),
    );
    assert.ok(response instanceof Response);
    return response;
  };
  const rejected = await send({
    ...input,
    unexpectedOperationField: "synthetic-value",
  });
  assert.equal(rejected.status, 400);
  assert.deepEqual(loaded.calls, []);
  assert.deepEqual(loaded.cookieWrites, []);
  const accepted = await send(input);
  assert.equal(accepted.status, 200);
  assert.equal(loaded.calls.length, 2);
  assert.equal(loaded.cookieWrites.length, 1);
});
void test("protected procedures still reject unauthenticated current inputs", async () => {
  const loaded = loadProtocol(new URL("./user.ts", import.meta.url));
  const caller = operationCaller(loaded, "user", false);
  await assert.rejects(
    async () => await invoke(property(caller, "get"), { id: "user" }),
    (error: unknown) =>
      error instanceof trpcServer.TRPCError && error.code === "UNAUTHORIZED",
  );
  assert.deepEqual(loaded.calls, []);
});
void test("audit defaults and patch omitted versus null fields reach the actual SDK boundary", async () => {
  const loaded = loadProtocol(new URL("./systemSettings.ts", import.meta.url));
  const caller = operationCaller(loaded, "systemSettings");
  await invoke(property(caller, "listAuditEvents"));
  assert.deepEqual(object(loaded.calls[0]?.request).query, {
    offset: 0,
    limit: 20,
  });
  await invoke(property(caller, "patchPlatformGitHubApp"), {
    expectedVersion: 3,
  });
  assert.deepEqual(object(object(loaded.calls[1]?.request).body), {
    expected_version: 3,
  });
  await invoke(property(caller, "patchPlatformGitHubApp"), {
    expectedVersion: 3,
    appId: null,
    privateKey: {
      action: "replace",
      value: "synthetic-key",
      retainedLegacyNestedField: "ignored",
    },
  });
  assert.deepEqual(object(object(loaded.calls[2]?.request).body), {
    expected_version: 3,
    app_id: null,
    private_key: { action: "replace", value: "synthetic-key" },
  });
});
void test("infrastructure nested maps and existing secret policies are unchanged", async () => {
  const loaded = loadProtocol(new URL("./runtimeProvider.ts", import.meta.url));
  const caller = operationCaller(loaded, "runtimeProvider");
  const spec = {
    profile_kind: "kubernetes_pod",
    contract_family: "kubernetes.pod-profile",
    schema_version: 3,
    runner_resources: {
      cpu_request_millicores: null,
      cpu_limit_millicores: null,
      memory_request_bytes: null,
      memory_limit_bytes: null,
    },
    workspace_volume: {
      storage_class_name: "standard",
      storage_request_bytes: 1,
    },
    service_account_name: null,
    scheduling: {
      node_selector: { "custom.example/zone": "one", "another/key": "two" },
    },
    dind: null,
    network_access: { mode: "no_network" },
  };
  await invoke(property(caller, "createInfrastructureProfile"), {
    ...profileInput,
    spec,
  });
  assert.deepEqual(object(object(loaded.calls[0]?.request).body).spec, spec);
});
