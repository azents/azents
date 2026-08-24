import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { SUPPORTED_LOCALES } from "../shared/lib/locale.ts";
import { MESSAGE_NAMESPACES } from "./message-composition.ts";

const messagesDirectory = fileURLToPath(
  new URL("../../messages/", import.meta.url),
);
const expectedFiles = MESSAGE_NAMESPACES.map(
  (namespace) => `${namespace}.json`,
).sort();

function collectMessageKeys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return [prefix];
  }

  return Object.entries(value).flatMap(([key, nestedValue]) =>
    collectMessageKeys(nestedValue, prefix === "" ? key : `${prefix}.${key}`),
  );
}

async function readNamespace(
  locale: string,
  namespace: string,
): Promise<unknown> {
  const contents = await readFile(
    `${messagesDirectory}/${locale}/${namespace}.json`,
    "utf8",
  );
  return JSON.parse(contents);
}

await test("every locale contains exactly the registered namespace files", async () => {
  for (const locale of SUPPORTED_LOCALES) {
    const actualFiles = (await readdir(`${messagesDirectory}/${locale}`))
      .filter((filename) => filename.endsWith(".json"))
      .sort();
    assert.deepEqual(actualFiles, expectedFiles, locale);
  }
});

await test("every locale namespace has the same recursive keys as en-US", async () => {
  for (const namespace of MESSAGE_NAMESPACES) {
    const referenceKeys = collectMessageKeys(
      await readNamespace("en-US", namespace),
    ).sort();

    for (const locale of SUPPORTED_LOCALES) {
      const localeKeys = collectMessageKeys(
        await readNamespace(locale, namespace),
      ).sort();
      assert.deepEqual(localeKeys, referenceKeys, `${locale}/${namespace}`);
    }
  }
});
