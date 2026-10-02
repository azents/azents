import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  normalizeExplicitToolkitSlug,
  resolveDefaultToolkitSlug,
  resolveToolkitName,
} from "./toolkit-identifiers.ts";
import type { ToolkitIdentifierValidationError } from "./toolkit-identifiers.ts";

interface NameCase {
  id: string;
  toolkit_type: string;
  canonical_name: string;
  submitted: string | null;
  expected?: string;
  error_field?: string;
}

interface DefaultSlugCase {
  id: string;
  effective_name: string;
  canonical_name: string;
  expected: string;
}

interface ExplicitSlugCase {
  id: string;
  submitted: string;
  expected?: string;
  reset?: boolean;
  error_field?: string;
}

interface Corpus {
  version: number;
  name_cases: NameCase[];
  default_slug_cases: DefaultSlugCase[];
  explicit_slug_cases: ExplicitSlugCase[];
}

const corpus = JSON.parse(
  readFileSync(
    new URL(
      "../../../../../../testdata/toolkit_identifier_conformance_v1.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as Corpus;

void test("shared Toolkit identifier corpus version is supported", () => {
  assert.equal(corpus.version, 1);
});

void test("Name resolution matches the shared corpus", () => {
  for (const item of corpus.name_cases) {
    const result = resolveToolkitName(
      item.toolkit_type,
      item.canonical_name,
      item.submitted,
    );
    if (item.error_field) {
      assert.equal(
        (result as ToolkitIdentifierValidationError).field,
        item.error_field,
        item.id,
      );
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
      assert.equal(
        (result as ToolkitIdentifierValidationError).field,
        item.error_field,
        item.id,
      );
    } else if (item.reset) {
      assert.equal(result, null, item.id);
    } else {
      assert.equal(result, item.expected, item.id);
    }
  }
});
