import assert from "node:assert/strict";
import { test } from "node:test";
import dayjs from "dayjs";
import {
  HookHarness,
  invoke,
  record,
} from "../../shared/testing/hook-harness.ts";

function nodes(value: unknown): Array<Record<string, unknown>> {
  if (value == null || typeof value !== "object") {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap(nodes);
  }
  const node = record(value);
  const props = record(node.props);
  if (typeof node.type === "function") {
    return nodes(invoke(node.type, props));
  }
  return [node, ...nodes(props.children)];
}

function render(emailState: unknown): {
  all: Array<Record<string, unknown>>;
  submitted: string[];
  changed: unknown[];
} {
  const submitted: string[] = [];
  const changed: unknown[] = [];
  const harness = new HookHarness();
  const components = Object.fromEntries(
    [
      "ActionIcon",
      "Alert",
      "Badge",
      "Box",
      "Button",
      "Center",
      "Group",
      "Loader",
      "Stack",
      "Text",
      "TextInput",
      "Title",
    ].map((name) => [name, name]),
  );
  const jsx = (type: unknown, props: unknown): unknown => ({ type, props });
  harness.load(
    new URL("./components/UserDetailView.tsx", import.meta.url),
    "UserDetailView",
    {
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "@mantine/core": {
        ...components,
        Table: { Thead: "Thead", Tr: "Tr", Th: "Th", Tbody: "Tbody", Td: "Td" },
      },
      "@tabler/icons-react": {
        IconAlertCircle: "IconAlertCircle",
        IconPlus: "IconPlus",
        IconShieldCheck: "IconShieldCheck",
        IconShieldOff: "IconShieldOff",
        IconTrash: "IconTrash",
      },
      dayjs,
    },
  );
  const user = {
    id: "user-1",
    primary_email: "before@example.com",
    created_at: "2026-10-15T00:00:00Z",
    updated_at: "2026-10-15T00:00:00Z",
  };
  const root = harness.render({
    state: { type: "VIEWING", user },
    roleState: {
      type: "READY",
      assigned: false,
      currentUser: false,
      finalAdmin: false,
      action: "IDLE",
    },
    emailState,
    emailDraft: "draft@example.com",
    onEmailDraftChange: (next: unknown) => changed.push(next),
    onSubmitEmail: () => submitted.push("submitted"),
    onDeleteEmail: () => {},
    onDelete: () => {},
    onGrantAdmin: () => {},
    onRevokeAdmin: () => {},
  });
  return { all: nodes(root), submitted, changed };
}

void test("actual pure user view forwards email draft input, Enter prevention and Add without owning state", () => {
  const { all, submitted, changed } = render({ type: "LOADED", emails: [] });
  const input = all.find((node) => node.type === "TextInput");
  assert.ok(input);
  const inputProps = record(input.props);
  assert.equal(inputProps.value, "draft@example.com");
  invoke(inputProps.onChange, {
    currentTarget: { value: "changed@example.com" },
  });
  assert.deepEqual(changed, ["changed@example.com"]);
  let prevented = 0;
  invoke(inputProps.onKeyDown, {
    key: "Enter",
    preventDefault: () => {
      prevented += 1;
    },
  });
  assert.equal(prevented, 1);
  const add = all.find(
    (node) => node.type === "Button" && record(node.props).children === "Add",
  );
  assert.ok(add);
  invoke(record(add.props).onClick);
  assert.deepEqual(submitted, ["submitted", "submitted"]);
});

void test("actual pure user view distinguishes email loading and error from an empty successful list", () => {
  const loading = render({ type: "LOADING" });
  assert.equal(
    loading.all.some((node) => node.type === "Loader"),
    true,
  );
  const error = render({ type: "ERROR", message: "Email query failed" });
  const errorText = error.all.find(
    (node) => node.type === "Text" && record(node.props).c === "red",
  );
  assert.ok(errorText);
  const errorChildren = record(errorText.props).children;
  assert.ok(Array.isArray(errorChildren));
  assert.deepEqual(Array.from(errorChildren), [
    "Error: ",
    "Email query failed",
  ]);
  assert.equal(
    error.all.some(
      (node) => record(node.props).children === "No email addresses found.",
    ),
    false,
  );
  const empty = render({ type: "LOADED", emails: [] });
  assert.equal(
    empty.all.some(
      (node) => record(node.props).children === "No email addresses found.",
    ),
    true,
  );
});
