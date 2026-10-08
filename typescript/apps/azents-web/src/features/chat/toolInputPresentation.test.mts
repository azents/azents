import assert from "node:assert/strict";
import { test } from "node:test";
import { toolInputPresentation } from "./toolInputPresentation.ts";

void test("object input is split into readable named fields", () => {
  assert.deepEqual(
    toolInputPresentation(
      JSON.stringify({
        path: "/workspace/example",
        content: 'first line\n"second line"\tvalue',
        enabled: false,
        offset: 0,
        option: null,
        empty: "",
        nested: { value: true },
        items: ["first", "second"],
      }),
    ),
    {
      type: "fields",
      fields: [
        { name: "path", text: "/workspace/example" },
        { name: "content", text: 'first line\n"second line"\tvalue' },
        { name: "enabled", text: "false" },
        { name: "offset", text: "0" },
        { name: "option", text: "null" },
        { name: "empty", text: '""' },
        { name: "nested", text: '{\n  "value": true\n}' },
        { name: "items", text: '[\n  "first",\n  "second"\n]' },
      ],
    },
  );
});

void test("empty object remains a valid empty field set", () => {
  assert.deepEqual(toolInputPresentation("{}"), { type: "fields", fields: [] });
});

void test("non-object, freeform, partial, and empty input are preserved exactly", () => {
  for (const input of [
    "",
    "*** Begin Patch\n*** End Patch",
    '{"partial":',
    "null",
    "false",
    "42",
    '"text"',
    "[1, 2]",
  ]) {
    assert.deepEqual(toolInputPresentation(input), {
      type: "text",
      text: input,
    });
  }
});
