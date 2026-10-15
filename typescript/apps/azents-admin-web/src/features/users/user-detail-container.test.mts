import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HookHarness,
  invoke,
  record,
} from "../../shared/testing/hook-harness.ts";
import * as systemAdminState from "./system-admin-state.ts";

function setup(failCreation = false): {
  harness: HookHarness;
  emailQuery: Record<string, unknown>;
  userQuery: Record<string, unknown>;
  created: unknown[];
  deleted: unknown[];
  confirmations: unknown[];
  invalidated: unknown[];
} {
  const harness = new HookHarness();
  const created: unknown[] = [];
  const deleted: unknown[] = [];
  const confirmations: unknown[] = [];
  const invalidated: unknown[] = [];
  const userQuery: Record<string, unknown> = {
    data: { id: "user-1", primary_email: "before@example.com" },
    isLoading: false,
    isError: false,
    error: null,
  };
  const emailQuery: Record<string, unknown> = {
    data: {
      items: [
        { id: "email-1", email: "before@example.com", verified_at: null },
      ],
    },
    isLoading: false,
    isError: false,
    error: null,
  };
  const mutation = (capture: unknown[]): { useMutation: () => unknown } => ({
    useMutation: () => ({
      isPending: false,
      mutate: (input: unknown, callbacks?: unknown) => {
        capture.push(record(input));
        if (callbacks != null && !(capture === created && failCreation)) {
          invoke(record(callbacks).onSuccess);
        }
      },
    }),
  });
  const invalidate = (input: unknown): Promise<void> => {
    invalidated.push(input);
    return Promise.resolve();
  };
  harness.load(
    new URL("./containers/useUserDetailContainer.ts", import.meta.url),
    "useUserDetailContainer",
    {
      react: harness.react,
      "@mantine/modals": {
        modals: {
          openConfirmModal: (value: unknown) => confirmations.push(value),
        },
      },
      "@mantine/notifications": { notifications: { show: () => {} } },
      "@refinedev/core": { useLogout: () => ({ mutate: () => {} }) },
      "../system-admin-state": systemAdminState,
      "@/trpc/client": {
        trpc: {
          useUtils: () => ({
            user: { list: { invalidate }, get: { invalidate } },
            systemRole: { list: { invalidate } },
            userEmail: { listByUser: { invalidate } },
          }),
          user: { get: { useQuery: () => userQuery }, delete: mutation([]) },
          systemRole: {
            list: {
              useQuery: () => ({
                data: { items: [] },
                isLoading: false,
                isError: false,
                error: null,
              }),
            },
            me: {
              useQuery: () => ({
                data: { user_id: "admin-1" },
                isLoading: false,
                isError: false,
                error: null,
              }),
            },
            grantAdmin: mutation([]),
            revokeAdmin: mutation([]),
          },
          userEmail: {
            listByUser: { useQuery: () => emailQuery },
            create: mutation(created),
            delete: mutation(deleted),
          },
        },
      },
    },
  );
  return {
    harness,
    emailQuery,
    userQuery,
    created,
    deleted,
    confirmations,
    invalidated,
  };
}

const props = { userId: "user-1", onDeleted: () => {} };

void test("actual user container projects loading, error, populated and empty email states", () => {
  const { harness, emailQuery } = setup();
  assert.equal(record(harness.render(props).emailState).type, "LOADED");
  emailQuery.isLoading = true;
  assert.equal(record(harness.render(props).emailState).type, "LOADING");
  emailQuery.isLoading = false;
  emailQuery.isError = true;
  emailQuery.error = { message: "Email access failed" };
  assert.deepEqual(record(harness.render(props).emailState), {
    type: "ERROR",
    message: "Email access failed",
  });
  emailQuery.isError = false;
  emailQuery.data = { items: [] };
  assert.equal(record(harness.render(props).emailState).type, "LOADED");
  assert.equal(
    record(harness.render(props).emailState).emails instanceof Array,
    true,
  );
});

void test("actual user container owns trim, submission, immediate clear and query invalidation", () => {
  const { harness, created, invalidated } = setup();
  let output = harness.render(props);
  invoke(output.onEmailDraftChange, "  next@example.com  ");
  output = harness.render(props);
  assert.equal(output.emailDraft, "  next@example.com  ");
  invoke(output.onSubmitEmail);
  assert.deepEqual(created, [{ user_id: "user-1", email: "next@example.com" }]);
  assert.equal(harness.render(props).emailDraft, "");
  assert.deepEqual(invalidated.map(record), [{ user_id: "user-1" }]);
  invoke(output.onEmailDraftChange, "   ");
  invoke(harness.render(props).onSubmitEmail);
  assert.equal(created.length, 1);
  assert.equal(harness.render(props).emailDraft, "   ");
});

void test("actual user container preserves the draft while visible and clears when its former view unmounts", () => {
  const { harness, userQuery } = setup();
  let output = harness.render(props);
  harness.flushEffects();
  invoke(output.onEmailDraftChange, "unsaved@example.com");
  assert.equal(harness.render(props).emailDraft, "unsaved@example.com");
  harness.flushEffects();
  assert.equal(harness.render(props).emailDraft, "unsaved@example.com");
  userQuery.isLoading = true;
  userQuery.data = null;
  output = harness.render(props);
  assert.equal(record(output.state).type, "LOADING");
  harness.flushEffects();
  assert.equal(harness.render(props).emailDraft, "");
});

void test("actual email deletion still requires confirmation and invalidates the originating user", () => {
  const { harness, deleted, confirmations, invalidated } = setup();
  invoke(harness.render(props).onDeleteEmail, "email-1");
  assert.equal(deleted.length, 0);
  assert.equal(confirmations.length, 1);
  invoke(record(confirmations[0]).onConfirm);
  assert.deepEqual(deleted, [{ email_id: "email-1" }]);
  assert.deepEqual(invalidated.map(record), [{ user_id: "user-1" }]);
});

void test("failed email creation retains the existing immediate draft clear without a success invalidation", () => {
  const { harness, created, invalidated } = setup(true);
  invoke(harness.render(props).onEmailDraftChange, "  failed@example.com  ");
  invoke(harness.render(props).onSubmitEmail);
  assert.deepEqual(created, [
    { user_id: "user-1", email: "failed@example.com" },
  ]);
  assert.equal(harness.render(props).emailDraft, "");
  assert.deepEqual(invalidated, []);
});

void test("cached visible user changes preserve draft lifetime while submission targets the current user", () => {
  const { harness, created } = setup();
  harness.render(props);
  harness.flushEffects();
  invoke(harness.render(props).onEmailDraftChange, "draft@example.com");
  const nextProps = { ...props, userId: "user-2" };
  let output = harness.render(nextProps);
  harness.flushEffects();
  output = harness.render(nextProps);
  assert.equal(output.emailDraft, "draft@example.com");
  invoke(output.onSubmitEmail);
  assert.deepEqual(created, [
    { user_id: "user-2", email: "draft@example.com" },
  ]);
});
