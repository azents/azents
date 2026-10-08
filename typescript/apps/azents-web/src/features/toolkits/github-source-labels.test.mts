import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { z } from "zod/v4";

const sourceLabels = z.object({
  toolkits: z.object({
    github: z.object({
      authTypeApp: z.string(),
      authTypePlatform: z.string(),
      authTypeUser: z.string(),
      authTypePlatformUser: z.string(),
      user: z.object({ byoa: z.string(), platform: z.string() }),
    }),
  }),
});

for (const locale of ["en-US", "ko-KR", "ja-JP", "fr-FR"]) {
  void test(`${locale} uses the same App source name for both authorities and details`, () => {
    const messages: unknown = JSON.parse(
      readFileSync(
        new URL(`../../../messages/${locale}/workspace.json`, import.meta.url),
        "utf8",
      ),
    );
    const labels = sourceLabels.parse(messages).toolkits.github;
    assert.ok(labels.authTypeApp.startsWith(labels.user.byoa));
    assert.ok(labels.authTypeUser.startsWith(labels.user.byoa));
    assert.ok(labels.authTypePlatform.startsWith(labels.user.platform));
    assert.ok(labels.authTypePlatformUser.startsWith(labels.user.platform));
    assert.notEqual(labels.authTypeApp, labels.authTypeUser);
    assert.notEqual(labels.authTypePlatform, labels.authTypePlatformUser);
    assert.ok(
      ![labels.authTypeApp, labels.authTypeUser, labels.user.byoa].some(
        (label) => label.includes("BYOA"),
      ),
    );
  });
}
