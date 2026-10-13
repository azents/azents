import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { z } from "zod/v4";

const guideSchema = z.object({
  steps: z.object({
    settings: z.object({ tokenExpiry: z.string() }),
  }),
});
const workspaceSchema = z.object({
  toolkits: z.object({
    github: z.object({
      userRegistrationInstructions: z.string(),
      platformUserInstructions: z.string(),
    }),
  }),
});
const locales = [
  {
    name: "en-US",
    location: /New GitHub App creation form/,
    action: /uncheck Expire user authorization tokens/,
  },
  {
    name: "ko-KR",
    location: /GitHub App을 만드는 화면/,
    action: /Expire user authorization tokens 체크를 해제/,
  },
  {
    name: "ja-JP",
    location: /GitHub App の作成画面/,
    action: /Expire user authorization tokens のチェックを外/,
  },
  {
    name: "fr-FR",
    location: /formulaire New GitHub App/,
    action: /décoche(?:z|r) Expire user authorization tokens/,
  },
];

for (const locale of locales) {
  void test(`${locale.name} identifies the creation-form expiry checkbox and instructs unchecking it`, () => {
    const guide = guideSchema.parse(
      JSON.parse(
        readFileSync(
          new URL(
            `../../../messages/${locale.name}/githubAppGuide.json`,
            import.meta.url,
          ),
          "utf8",
        ),
      ),
    );
    const workspace = workspaceSchema.parse(
      JSON.parse(
        readFileSync(
          new URL(
            `../../../messages/${locale.name}/workspace.json`,
            import.meta.url,
          ),
          "utf8",
        ),
      ),
    );
    for (const instruction of [
      guide.steps.settings.tokenExpiry,
      workspace.toolkits.github.userRegistrationInstructions,
      workspace.toolkits.github.platformUserInstructions,
    ]) {
      assert.match(instruction, locale.location);
      assert.match(instruction, locale.action);
      assert.doesNotMatch(
        instruction,
        /Optional Features|User-to-server token expiration|Opt-out/,
      );
    }
    assert.ok(guide.steps.settings.tokenExpiry.includes("Create GitHub App"));
  });
}
