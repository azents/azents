import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HookHarness,
  invoke,
  object,
} from "../../../shared/testing/hook-test-harness.ts";
import { projectAgentSessionDirectoryQueryState } from "../agent-session-directory-state.ts";

function setup(
  file: string,
  hook: string,
): {
  harness: HookHarness;
  calls: unknown[];
  complete: () => void;
} {
  const calls: unknown[] = [];
  let success: (() => void) | null = null;
  const invalidate = (
    name: string,
  ): { invalidate: (input: unknown) => void } => ({
    invalidate: (input): void => {
      calls.push([name, object(input)]);
    },
  });
  const query = {
    useQuery: (): unknown => ({
      data: void 0,
      isPending: false,
      isError: false,
      isLoading: false,
      error: null,
    }),
  };
  const mutation = {
    useMutation: (options: Record<string, unknown> = {}): unknown => ({
      isPending: false,
      error: null,
      reset: (): void => {},
      mutate: (input: unknown, local: Record<string, unknown> = {}): void => {
        success = (): void => {
          invoke(local.onSuccess ?? options.onSuccess, {}, input);
        };
      },
    }),
  };
  const harness = new HookHarness();
  harness.load(
    new URL(file, import.meta.url),
    hook,
    {
      react: harness.react,
      "next-intl": {
        useTranslations:
          (): unknown =>
          (key: string): string =>
            key,
      },
      "@mantine/hooks": {
        useDisclosure: (): unknown => [
          false,
          { open: (): void => {}, close: (): void => {} },
        ],
      },
      "next/navigation": {
        useRouter: (): unknown => ({
          push: (path: string): void => {
            calls.push(["push", path]);
          },
          replace: (path: string): void => {
            calls.push(["replace", path]);
          },
        }),
        usePathname: (): string =>
          "/w/preview/agents/agent-preview/sessions/session-preview",
        useSearchParams: (): URLSearchParams => new URLSearchParams(),
      },
      "@/shared/agent-session/useAgentLifecycle": {
        useAgentLifecycle: (): unknown => ({ agent: { id: "agent-preview" } }),
      },
      "../agent-session-directory-state": {
        projectAgentSessionDirectoryQueryState,
      },
      "@/trpc/client": {
        trpc: {
          useUtils: (): unknown => ({
            agent: {
              list: invalidate("agent-list"),
              get: invalidate("agent-get"),
            },
            chat: {
              listAgentSessions: invalidate("sessions"),
              getAgentSessionSidebar: invalidate("sidebar"),
              listAgentUserSessions: invalidate("user-sessions"),
              getAgentSession: invalidate("session-get"),
            },
          }),
          agent: { remove: mutation },
          chat: {
            listAgentSessions: query,
            getAgentSessionSidebar: query,
            listAgentUserSessions: query,
            getAgentSession: query,
            updateAgentSessionTitle: mutation,
            updateAgentSessionPin: mutation,
            archiveAgentSession: mutation,
            restoreAgentSession: mutation,
          },
          user: { me: query, adminAccess: query },
          memberProfile: { getMyProfile: query },
          auth: { logout: mutation },
        },
      },
    },
    null,
    void 0,
    { URLSearchParams },
  );
  return {
    harness,
    calls,
    complete: (): void => {
      if (success === null) {
        throw new Error("No pending mutation");
      }
      success();
    },
  };
}

void test("agent deletion invalidates list and exact detail before navigation", () => {
  const { harness, calls, complete } = setup(
    "./useAgentDangerSectionController.tsx",
    "useAgentDangerSectionController",
  );
  const output = object(
    harness.render({
      readOnly: false,
      handle: "preview",
      agentId: "agent-preview",
    }),
  );
  invoke(output.handleDelete);
  assert.deepEqual(calls, []);
  complete();
  assert.deepEqual(calls, [
    ["agent-list", { handle: "preview" }],
    ["agent-get", { handle: "preview", agentId: "agent-preview" }],
    ["push", "/w/preview/agents"],
  ]);
});

for (const action of [
  "onArchiveSession",
  "onSetSessionPinned",
  "onRestoreSession",
]) {
  void test(`${action} invalidates its exact Session and both directory projections`, () => {
    const { harness, calls, complete } = setup(
      "./useAgentSessionDirectoryContainer.ts",
      "useAgentSessionDirectoryContainer",
    );
    const output = object(
      harness.render({ handle: "preview", agent: { id: "agent-preview" } }),
    );
    invoke(output[action], "session-preview", true);
    assert.deepEqual(calls, []);
    complete();
    assert.deepEqual(calls, [
      ["sessions", { agentId: "agent-preview" }],
      ["sidebar", { agentId: "agent-preview" }],
      [
        "session-get",
        { agentId: "agent-preview", sessionId: "session-preview" },
      ],
    ]);
  });
}

void test("focused archive invalidates exact detail before replacing the active route", () => {
  const { harness, calls, complete } = setup(
    "./useAgentFocusedShellController.tsx",
    "useAgentFocusedShellController",
  );
  const output = object(
    harness.render({
      handle: "preview",
      agent: { id: "agent-preview" },
      children: null,
    }),
  );
  invoke(object(output.sidebarProps).onArchiveSession, "session-preview");
  assert.deepEqual(calls, []);
  complete();
  assert.deepEqual(calls, [
    ["sessions", { agentId: "agent-preview" }],
    ["sidebar", { agentId: "agent-preview" }],
    ["user-sessions", { agentId: "agent-preview" }],
    ["session-get", { agentId: "agent-preview", sessionId: "session-preview" }],
    ["replace", "/w/preview/agents/agent-preview/sessions/new"],
  ]);
});
