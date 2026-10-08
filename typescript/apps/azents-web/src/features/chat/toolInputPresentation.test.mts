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

void test("numeric lexemes remain exact at every nesting level", () => {
  assert.deepEqual(
    toolInputPresentation(
      '{"request_id":9007199254740993,"precise":0.123456789012345678901,"exponent":1e+999,"negative_zero":-0,"nested":{"ids":[9007199254740993,1.2300e+40]},"empty":{"list":[],"object":{}}}',
    ),
    {
      type: "fields",
      fields: [
        { name: "request_id", text: "9007199254740993" },
        { name: "precise", text: "0.123456789012345678901" },
        { name: "exponent", text: "1e+999" },
        { name: "negative_zero", text: "-0" },
        {
          name: "nested",
          text: '{\n  "ids": [\n    9007199254740993,\n    1.2300e+40\n  ]\n}',
        },
        { name: "empty", text: '{\n  "list": [],\n  "object": {}\n}' },
      ],
    },
  );
});

void test("escaped punctuation and duplicate field names remain readable", () => {
  assert.deepEqual(
    toolInputPresentation('{"a":1,"a":2,"punctuation":"[{},:] \\"quoted\\""}'),
    {
      type: "fields",
      fields: [
        { name: "a", text: "1" },
        { name: "a", text: "2" },
        { name: "punctuation", text: '[{},:] "quoted"' },
      ],
    },
  );
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
