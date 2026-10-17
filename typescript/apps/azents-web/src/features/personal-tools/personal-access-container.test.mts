import assert from "node:assert/strict";
import test from "node:test";
import {
  HookHarness,
  invoke,
  object,
} from "../../shared/testing/hook-test-harness.ts";
import * as drafts from "./access-draft.ts";
import { personalToolFixture } from "./personal-tools-fixtures.ts";
import type { PersonalAccessTarget } from "./types.ts";

function fixture(target: PersonalAccessTarget): {
  h: HookHarness;
  calls: Array<{ route: string; input: unknown }>;
  invalidations: string[];
  navigations: string[];
  fail: (conflict: boolean) => void;
  replacePolicy: () => void;
} {
  const h = new HookHarness();
  const calls: Array<{ route: string; input: unknown }> = [];
  const invalidations: string[] = [];
  const navigations: string[] = [];
  let failure: boolean | null = null;
  let connection = personalToolFixture();
  const connections = [
    personalToolFixture(),
    personalToolFixture({
      id: "selected",
      access_mode: "selected",
      selected_agent_ids: ["unavailable"],
    }),
  ];
  const query = (data: () => unknown): unknown => ({
    useQuery: (_input: unknown, options?: { enabled: boolean }): unknown => ({
      data: options?.enabled === false ? void 0 : data(),
      isError: false,
    }),
  });
  const mutation = (route: string): unknown => ({
    useMutation: () => ({
      mutateAsync: (input: unknown): Promise<unknown> => {
        calls.push({ route, input });
        return failure === null
          ? Promise.resolve({})
          : Promise.reject(
              Object.assign(new Error("Fixture save failed"), {
                data: { code: failure ? "CONFLICT" : "INTERNAL_SERVER_ERROR" },
              }),
            );
      },
    }),
  });
  const invalidator = (name: string): unknown => ({
    invalidate: (): Promise<void> => {
      invalidations.push(name);
      return Promise.resolve();
    },
  });
  h.load(
    new URL("./containers/usePersonalAccessContainer.ts", import.meta.url),
    "usePersonalAccessContainer",
    {
      react: h.react,
      "next/navigation": {
        useRouter: () => ({ push: (path: string) => navigations.push(path) }),
      },
      "../access-draft": drafts,
      "@/trpc/client": {
        trpc: {
          user: { me: query(() => ({ email: "owner@example.com" })) },
          personalToolkit: {
            get: query(() => connection),
            eligibleAgents: query(() => ({
              items: [
                {
                  agent_id: "agent-a",
                  agent_name: "Assistant",
                  description: "Researches primary sources.",
                  avatar: null,
                  workspace_id: "w-a",
                  workspace_name: "Workspace",
                },
                {
                  agent_id: "agent-b",
                  agent_name: "Writer",
                  workspace_id: "w-a",
                  workspace_name: "Workspace",
                },
              ],
            })),
            accessForAgent: query(() => ({ items: connections })),
            saveAccess: mutation("connection"),
            saveAccessForAgent: mutation("agent"),
          },
          useUtils: () => ({
            user: { me: invalidator("me") },
            personalToolkit: Object.fromEntries(
              ["list", "get", "accessForAgent", "eligibleAgents"].map(
                (name) => [name, invalidator(name)],
              ),
            ),
          }),
        },
      },
    },
    {},
  );
  h.render(target);
  return {
    h,
    calls,
    invalidations,
    navigations,
    fail: (conflict) => {
      failure = conflict;
    },
    replacePolicy: () => {
      connection = personalToolFixture({
        access_mode: "selected",
        selected_agent_ids: [],
      });
    },
  };
}

function plain(value: unknown): unknown {
  return JSON.parse(JSON.stringify(value));
}

for (const action of ["save", "cancel", "failed-save"] as const) {
  void test(`Composer-origin ${action} returns only after acknowledged completion`, async () => {
    const f = fixture({
      type: "agent",
      handle: "workspace",
      agentId: "agent-a",
      agentName: "Assistant",
      originSessionId: "session-a",
    });
    invoke(f.h.render().onToggle, "personal-example", false);
    if (action === "failed-save") {
      f.fail(false);
    }
    await invoke(
      action === "cancel" ? f.h.render().onCancel : f.h.render().onSave,
    );
    assert.deepEqual(
      f.navigations,
      action === "failed-save"
        ? []
        : ["/w/workspace/agents/agent-a/sessions/session-a"],
    );
    if (action === "cancel") {
      assert.equal(f.calls.length, 0);
    }
    if (action === "failed-save") {
      assert.equal(f.h.render().dirty, true);
    }
  });
}

void test("Connection editor lists same-Workspace Agents and keeps the first restriction independent of search", async () => {
  const f = fixture({
    type: "connection",
    handle: "workspace",
    toolkitId: "personal-example",
  });
  let view = f.h.render();
  assert.equal(object(view.state).type, "READY");
  invoke(view.onToggle, "agent-a", false);
  view = f.h.render();
  assert.equal(object(view.state).firstRestriction, true);
  invoke(view.onSearch, "Writer");
  view = f.h.render();
  const groups = object(view.state).groups;
  assert.ok(Array.isArray(groups));
  assert.equal(groups.length, 1);
  await invoke(view.onSave);
  assert.deepEqual(plain(f.calls), [
    {
      route: "connection",
      input: {
        handle: "workspace",
        toolkitId: "personal-example",
        expected_mode: "all",
        mode: "selected",
        allow_agent_ids: [],
        restrict_agent_ids: ["agent-a"],
      },
    },
  ]);
  assert.deepEqual(f.invalidations.sort(), [
    "accessForAgent",
    "eligibleAgents",
    "get",
    "list",
  ]);
  assert.equal(f.h.render().dirty, false);
});

void test("Cancel discards local drafts without any permission mutation or read invalidation", () => {
  const f = fixture({
    type: "agent",
    handle: "workspace",
    agentId: "agent-a",
    agentName: "Assistant",
  });
  invoke(f.h.render().onToggle, "personal-example", false);
  const view = f.h.render();
  assert.equal(view.dirty, true);
  invoke(view.onCancel);
  assert.equal(f.h.render().dirty, false);
  assert.equal(f.calls.length, 0);
  assert.equal(f.invalidations.length, 0);
});

for (const conflict of [false, true]) {
  void test(`Failed Agent save keeps its full draft; conflict=${conflict}`, async () => {
    const f = fixture({
      type: "agent",
      handle: "workspace",
      agentId: "agent-a",
      agentName: "Assistant",
    });
    f.fail(conflict);
    invoke(f.h.render().onToggle, "personal-example", false);
    invoke(f.h.render().onToggle, "selected", true);
    await invoke(f.h.render().onSave);
    const view = f.h.render();
    assert.deepEqual(plain(view.write), { type: "ERROR", conflict });
    assert.equal(view.dirty, true);
    assert.equal(f.invalidations.length, 0);
    assert.equal(f.calls.length, 1);
    assert.ok(f.calls[0]);
    assert.deepEqual(plain(f.calls[0].input), {
      handle: "workspace",
      agentId: "agent-a",
      mutations: [
        {
          toolkit_id: "personal-example",
          expected_mode: "all",
          mode: null,
          allow_agent_ids: [],
          restrict_agent_ids: ["agent-a"],
        },
        {
          toolkit_id: "selected",
          expected_mode: "selected",
          mode: null,
          allow_agent_ids: ["agent-a"],
          restrict_agent_ids: [],
        },
      ],
    });
  });
}

void test("Background policy changes never overwrite the loaded draft mode precondition", async () => {
  const f = fixture({
    type: "connection",
    handle: "workspace",
    toolkitId: "personal-example",
  });
  invoke(f.h.render().onToggle, "agent-a", false);
  f.replacePolicy();
  await invoke(f.h.render().onSave);
  assert.ok(f.calls[0]);
  assert.equal(object(f.calls[0].input).expected_mode, "all");
});
