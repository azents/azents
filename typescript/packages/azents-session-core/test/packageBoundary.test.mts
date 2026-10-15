import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const sourceDirectory = resolve(
  fileURLToPath(new URL("../src/", import.meta.url)),
);

void test("production modules depend only on package sources and type-only Public API contracts", () => {
  const files = readdirSync(sourceDirectory).filter((name) =>
    name.endsWith(".ts"),
  );
  assert.ok(files.length > 0);
  for (const file of files) {
    const path = resolve(sourceDirectory, file);
    const source = ts.createSourceFile(
      path,
      readFileSync(path, "utf8"),
      ts.ScriptTarget.Latest,
      true,
    );
    for (const statement of source.statements) {
      if (
        !ts.isImportDeclaration(statement) &&
        !ts.isExportDeclaration(statement)
      ) {
        continue;
      }
      const module = statement.moduleSpecifier;
      if (module === undefined) {
        continue;
      }
      assert.ok(ts.isStringLiteral(module), `${file}: static module specifier`);
      const specifier = module.text;
      if (specifier === "@azents/public-client/types") {
        const typeOnly = ts.isImportDeclaration(statement)
          ? statement.importClause?.isTypeOnly
          : statement.isTypeOnly;
        assert.equal(
          typeOnly,
          true,
          `${file}: generated client supplies types only`,
        );
        continue;
      }
      assert.ok(
        specifier.startsWith("./"),
        `${file}: host dependency ${specifier}`,
      );
      assert.equal(
        dirname(resolve(sourceDirectory, specifier)),
        sourceDirectory,
      );
      assert.ok(
        files.includes(specifier.slice(2)),
        `${file}: local module ${specifier}`,
      );
    }
  }
});
