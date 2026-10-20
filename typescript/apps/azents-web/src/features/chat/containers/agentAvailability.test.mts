import assert from "node:assert/strict";
import test from "node:test";
import {
  isCancelledError,
  QueryClient,
  QueryObserver,
} from "@tanstack/react-query";
import {
  deferred,
  HookHarness,
  invoke,
  object,
} from "../../../shared/testing/hook-test-harness.ts";

interface AgentFixture {
  id: string;
  browser_enabled: boolean;
  deletion_status?: "deleting" | "deletion_error" | null;
}

function agentFixture(value: unknown): AgentFixture {
  const data = object(value);
  return {
    id: String(data.id),
    browser_enabled: data.browser_enabled === true,
    ...(data.deletion_status === "deleting" ||
    data.deletion_status === "deletion_error" ||
    data.deletion_status === null
      ? { deletion_status: data.deletion_status }
      : {}),
  };
}
function fixture(cached: AgentFixture): {
  hook: HookHarness;
  client: QueryClient;
  key: string[];
  options: Array<Record<string, unknown>>;
  seeded: Promise<AgentFixture>;
  writes: AgentFixture[];
  scrollStyles: Array<{ overflow: string; overscrollBehavior: string }>;
} {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 300_000,
        refetchOnWindowFocus: false,
        retry: false,
      },
    },
  });
  const key = ["agent", cached.id];
  client.setQueryData(key, cached, { updatedAt: 100 });
  const hook = new HookHarness();
  const options: Array<Record<string, unknown>> = [];
  const seeded = deferred<AgentFixture>();
  const writes: AgentFixture[] = [];
  const scrollStyles = [
    { overflow: "auto", overscrollBehavior: "contain" },
    { overflow: "scroll", overscrollBehavior: "auto" },
  ];
  const utils = {
    agent: {
      get: {
        cancel: (): Promise<void> => client.cancelQueries({ queryKey: key }),
        setData: (_input: unknown, value: unknown): void => {
          const agent = agentFixture(
            typeof value === "function"
              ? invoke(value, client.getQueryData(key))
              : value,
          );
          client.setQueryData(key, agent);
          writes.push(agent);
          seeded.resolve(agent);
        },
        invalidate: (): Promise<void> =>
          client.invalidateQueries({ queryKey: key, refetchType: "none" }),
      },
    },
  };
  hook.load(
    new URL("./useAgentChatContainer.ts", import.meta.url),
    "useAgentChatContainer",
    {
      react: hook.react,
      "next/navigation": { useRouter: () => ({ replace: () => {} }) },
      "@/trpc/client": {
        trpc: {
          useUtils: () => utils,
          agent: {
            get: {
              useQuery: (_input: unknown, settings: unknown): unknown => {
                const opts = object(settings);
                options.push(opts);
                const initial = object(opts.initialData);
                return new QueryObserver<AgentFixture>(client, {
                  queryKey: key,
                  initialData: agentFixture(initial),
                  queryFn: () => Promise.resolve(cached),
                }).getCurrentResult();
              },
            },
          },
          chat: {
            getAgentSession: {
              useQuery: (): unknown => ({ data: { id: "session" } }),
            },
          },
        },
      },
    },
    {},
    {
      documentElement: { style: scrollStyles[0] },
      body: { style: scrollStyles[1] },
    },
  );
  return {
    hook,
    client,
    key,
    options,
    seeded: seeded.promise,
    writes,
    scrollStyles,
  };
}
function props(agent: AgentFixture): Record<string, unknown> {
  return {
    agent,
    handle: "team",
    sessionId: "session",
    session: { id: "session" },
    renderSupportingContent: () => null,
  };
}

void test("stale server hydration preserves a known deletion error", async () => {
  const cached: AgentFixture = {
    id: "deleting-agent",
    browser_enabled: true,
    deletion_status: "deletion_error",
  };
  const { hook, client, key, seeded } = fixture(cached);
  hook.render(
    props({ ...cached, browser_enabled: false, deletion_status: null }),
  );
  hook.flushEffects();
  await seeded;
  assert.equal(
    object(client.getQueryData(key)).deletion_status,
    "deletion_error",
  );
  assert.equal(object(hook.render().agent).deletion_status, "deletion_error");
  hook.unmount();
  client.clear();
});

void test("chat container owns and restores the document scroll lifecycle", () => {
  const agent = { id: "scroll-agent", browser_enabled: false };
  const { hook, client, scrollStyles } = fixture(agent);
  hook.render(props(agent));
  hook.flushEffects();
  assert.deepEqual(scrollStyles, [
    { overflow: "hidden", overscrollBehavior: "none" },
    { overflow: "hidden", overscrollBehavior: "none" },
  ]);
  hook.unmount();
  assert.deepEqual(scrollStyles, [
    { overflow: "auto", overscrollBehavior: "contain" },
    { overflow: "scroll", overscrollBehavior: "auto" },
  ]);
  client.clear();
});

void test("cached enabled Agent cannot override fresh disabled server props before or after hydration", async () => {
  const cached = { id: "agent", browser_enabled: true };
  const { hook, client, key, options, seeded } = fixture(cached);
  const disabled = { id: "agent", browser_enabled: false };
  assert.equal(
    object(hook.render(props(disabled)).agent).browser_enabled,
    false,
  );
  assert.equal(object(client.getQueryData(key)).browser_enabled, true);
  const queryOptions = options[0];
  assert.ok(queryOptions);
  assert.equal(queryOptions.staleTime, 0);
  assert.equal(queryOptions.refetchOnMount, false);
  assert.equal(queryOptions.refetchOnWindowFocus, true);
  hook.flushEffects();
  await seeded;
  assert.equal(object(hook.render().agent).browser_enabled, false);
  assert.equal(object(client.getQueryData(key)).browser_enabled, false);
  client.setQueryData(key, cached);
  assert.equal(object(hook.render().agent).browser_enabled, true);
  assert.equal(
    object(hook.render({ ...props(disabled), handle: "renamed" }).agent)
      .browser_enabled,
    false,
  );
  assert.equal(
    object(hook.render(props({ ...disabled })).agent).browser_enabled,
    false,
  );
  hook.unmount();
  client.clear();
});

void test("new server enablement and subsequent current query disablement both propagate", async () => {
  const { hook, client, key, seeded } = fixture({
    id: "agent",
    browser_enabled: false,
  });
  const enabled = { id: "agent", browser_enabled: true };
  assert.equal(object(hook.render(props(enabled)).agent).browser_enabled, true);
  hook.flushEffects();
  await seeded;
  assert.equal(object(hook.render().agent).browser_enabled, true);
  client.setQueryData(key, { id: "agent", browser_enabled: false });
  assert.equal(object(hook.render().agent).browser_enabled, false);
  hook.unmount();
  client.clear();
});

void test("a delayed pre-boundary enabled read is cancelled and cannot restore Browser UI", async () => {
  const cached = { id: "agent", browser_enabled: true };
  const { hook, client, key, seeded } = fixture(cached);
  const pending = deferred<AgentFixture>();
  const started = deferred<void>();
  const oldRead = client
    .fetchQuery({
      queryKey: key,
      staleTime: 0,
      queryFn: () => {
        started.resolve();
        return pending.promise;
      },
    })
    .catch((error: unknown) => {
      assert.ok(isCancelledError(error));
      return null;
    });
  await started.promise;
  assert.equal(client.getQueryState(key)?.fetchStatus, "fetching");
  const disabled = { id: "agent", browser_enabled: false };
  assert.equal(
    object(hook.render(props(disabled)).agent).browser_enabled,
    false,
  );
  hook.flushEffects();
  await seeded;
  assert.equal(client.getQueryState(key)?.fetchStatus, "idle");
  pending.resolve(cached);
  await pending.promise;
  await oldRead;
  assert.equal(object(client.getQueryData(key)).browser_enabled, false);
  assert.equal(object(hook.render().agent).browser_enabled, false);
  hook.unmount();
  client.clear();
});

void test("superseded server hydration cannot overwrite the next disabled props", async () => {
  const { hook, client, key, seeded, writes } = fixture({
    id: "agent",
    browser_enabled: true,
  });
  hook.render(props({ id: "agent", browser_enabled: true }));
  hook.flushEffects();
  hook.render(props({ id: "agent", browser_enabled: false }));
  hook.flushEffects();
  assert.equal((await seeded).browser_enabled, false);
  assert.deepEqual(
    writes.map((value) => value.browser_enabled),
    [false],
  );
  assert.equal(object(client.getQueryData(key)).browser_enabled, false);
  assert.equal(object(hook.render().agent).browser_enabled, false);
  hook.unmount();
  client.clear();
});
