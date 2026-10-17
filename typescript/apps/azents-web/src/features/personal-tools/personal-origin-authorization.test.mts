import assert from "node:assert/strict";
import test from "node:test";
import { TRPCError } from "@trpc/server";
import { HookHarness, invoke } from "../../shared/testing/hook-test-harness.ts";
import * as navigation from "./navigation.ts";

for (const outcome of [
  "allowed",
  "NOT_FOUND",
  "FORBIDDEN",
  "UNAUTHORIZED",
  "INTERNAL_SERVER_ERROR",
] as const) {
  void test(`Setup return reauthorizes the exact current Agent: ${outcome}`, async () => {
    const calls: unknown[] = [];
    const h = new HookHarness();
    const resolve = h.load(
      new URL("./resolve-personal-origin.ts", import.meta.url),
      "resolvePersonalToolsOrigin",
      {
        "server-only": {},
        "@trpc/server": { TRPCError },
        "./navigation": navigation,
        "@/trpc/server": {
          trpc: {
            agent: {
              get: (input: unknown): Promise<unknown> => {
                calls.push(input);
                if (outcome !== "allowed") {
                  return Promise.reject(new TRPCError({ code: outcome }));
                }
                return Promise.resolve({ id: "agent-a" });
              },
            },
          },
        },
      },
      {},
    );
    const result = invoke(
      resolve,
      {
        originHandle: "research",
        originAgentId: "agent-a",
        returnTo: "https://foreign.test",
      },
      "research",
    );
    if (outcome === "INTERNAL_SERVER_ERROR") {
      await assert.rejects(Promise.resolve(result));
    } else {
      assert.equal(
        JSON.stringify(await result),
        JSON.stringify(
          outcome === "allowed"
            ? { handle: "research", agentId: "agent-a" }
            : null,
        ),
      );
    }
    assert.equal(calls.length, 1);
    assert.equal(
      JSON.stringify(calls),
      '[{"handle":"research","agentId":"agent-a"}]',
    );
  });
}

for (const allowed of [true, false]) {
  void test(`Setup conversation origin requires exact current Session access: ${allowed}`, async () => {
    const calls: unknown[] = [];
    const h = new HookHarness();
    const resolve = h.load(
      new URL("./resolve-personal-origin.ts", import.meta.url),
      "resolvePersonalToolsOrigin",
      {
        "server-only": {},
        "@trpc/server": { TRPCError },
        "./navigation": navigation,
        "@/trpc/server": {
          trpc: {
            agent: {
              get: (): Promise<unknown> => Promise.resolve({ id: "agent-a" }),
            },
            chat: {
              getAgentSession: (input: unknown): Promise<unknown> => {
                calls.push(input);
                return allowed
                  ? Promise.resolve({})
                  : Promise.reject(new TRPCError({ code: "FORBIDDEN" }));
              },
            },
          },
        },
      },
      {},
    );
    const result = await invoke(
      resolve,
      {
        originHandle: "research",
        originAgentId: "agent-a",
        originSession: "session-a",
      },
      "research",
    );
    assert.equal(
      JSON.stringify(result),
      JSON.stringify(
        allowed
          ? { handle: "research", agentId: "agent-a", sessionId: "session-a" }
          : null,
      ),
    );
    assert.equal(
      JSON.stringify(calls),
      '[{"agentId":"agent-a","sessionId":"session-a"}]',
    );
  });
}
