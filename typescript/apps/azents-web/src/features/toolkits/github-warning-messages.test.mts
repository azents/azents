import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createTranslator } from "next-intl";
import { z } from "zod/v4";

const messageSchema = z.object({
  toolkits: z.object({
    github: z.object({
      runtimeEnvironmentWarningBody: z.string(),
      runtimeEnvironmentToggleDescription: z.string(),
    }),
  }),
});

void test("GitHub Runtime warning messages preserve literal installation IDs in every locale", async () => {
  for (const locale of ["en-US", "fr-FR", "ja-JP", "ko-KR"]) {
    const messages = messageSchema.parse(
      JSON.parse(
        await readFile(
          new URL(
            `../../../messages/${locale}/workspace.json`,
            import.meta.url,
          ),
          "utf8",
        ),
      ),
    );
    const errors: unknown[] = [];
    const t = createTranslator({
      locale,
      messages,
      namespace: "toolkits.github",
      onError: (error) => errors.push(error),
    });
    const warningKeys: Array<keyof typeof messages.toolkits.github> = [
      "runtimeEnvironmentWarningBody",
      "runtimeEnvironmentToggleDescription",
    ];
    for (const key of warningKeys) {
      const text = t(key);
      assert.ok(text.includes("GITHUB_TOKEN_INSTALLATION_<id>"), locale);
      assert.equal(text.includes("workspace.toolkits.github."), false, locale);
    }
    assert.deepEqual(errors, [], locale);
  }
});
