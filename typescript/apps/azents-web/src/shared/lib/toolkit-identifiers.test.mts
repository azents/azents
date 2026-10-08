import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { z } from "zod/v4";
import {
  normalizeExplicitToolkitSlug,
  resolveDefaultToolkitSlug,
  resolveToolkitName,
} from "./toolkit-identifiers.ts";

const nameCaseSchema = z
  .strictObject({
    id: z.string().min(1),
    toolkit_type: z.string().min(1),
    canonical_name: z.string().min(1),
    submitted: z.string().nullable(),
    expected: z.string().optional(),
    error_field: z.literal("name").optional(),
  })
  .refine(
    (item) => (item.expected !== void 0) !== (item.error_field !== void 0),
    "A Name case must declare exactly one expected outcome.",
  );

const explicitSlugCaseSchema = z
  .strictObject({
    id: z.string().min(1),
    submitted: z.string(),
    expected: z.string().optional(),
    reset: z.literal(true).optional(),
    error_field: z.literal("slug").optional(),
  })
  .refine(
    (item) =>
      [
        item.expected !== void 0,
        item.reset === true,
        item.error_field !== void 0,
      ].filter(Boolean).length === 1,
    "An explicit Slug case must declare exactly one expected outcome.",
  );

const corpusSchema = z.strictObject({
  version: z.literal(1),
  name_cases: z.array(nameCaseSchema),
  default_slug_cases: z.array(
    z.strictObject({
      id: z.string().min(1),
      effective_name: z.string(),
      canonical_name: z.string().min(1),
      expected: z.string(),
    }),
  ),
  explicit_slug_cases: z.array(explicitSlugCaseSchema),
});

const corpus = corpusSchema.parse(
  JSON.parse(
    readFileSync(
      new URL(
        "../../../../../../testdata/toolkit_identifier_conformance_v1.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ),
);

void test("shared Toolkit identifier corpus version is supported", () => {
  assert.equal(corpus.version, 1);
});

void test("the corpus decoder rejects malformed fields and ambiguous outcomes", () => {
  for (const malformed of [
    { ...corpus, version: 2 },
    { ...corpus, unexpected: true },
    { ...corpus, name_cases: [{ id: "missing-fields" }] },
    {
      ...corpus,
      name_cases: [
        {
          id: "ambiguous-name",
          toolkit_type: "mcp",
          canonical_name: "MCP",
          submitted: null,
          expected: "MCP",
          error_field: "name",
        },
      ],
    },
    {
      ...corpus,
      explicit_slug_cases: [{ id: "missing-outcome", submitted: "valid_slug" }],
    },
    {
      ...corpus,
      explicit_slug_cases: [
        { id: "ambiguous-reset", submitted: "", reset: true, expected: "" },
      ],
    },
  ]) {
    assert.equal(corpusSchema.safeParse(malformed).success, false);
  }
});

void test("Name resolution matches the shared corpus", () => {
  for (const item of corpus.name_cases) {
    const result = resolveToolkitName(
      item.toolkit_type,
      item.canonical_name,
      item.submitted,
    );
    if (item.error_field) {
      assert.ok(typeof result === "object", item.id);
      assert.equal(result.field, item.error_field, item.id);
    } else {
      assert.equal(result, item.expected, item.id);
    }
  }
});

void test("default Slug resolution matches the shared corpus", () => {
  for (const item of corpus.default_slug_cases) {
    assert.equal(
      resolveDefaultToolkitSlug(item.effective_name, item.canonical_name),
      item.expected,
      item.id,
    );
  }
});

void test("explicit Slug normalization matches the shared corpus", () => {
  for (const item of corpus.explicit_slug_cases) {
    const result = normalizeExplicitToolkitSlug(item.submitted);
    if (item.error_field) {
      assert.ok(typeof result === "object" && result !== null, item.id);
      assert.equal(result.field, item.error_field, item.id);
    } else if (item.reset) {
      assert.equal(result, null, item.id);
    } else {
      assert.equal(result, item.expected, item.id);
    }
  }
});
