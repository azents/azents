import assert from "node:assert/strict";
import test from "node:test";
import {
  discordSuppressUrlPreviewsFromConfiguration,
  discordThreadAutoArchiveDurationFromConfiguration,
} from "./discord-thread-auto-archive-duration.ts";

void test("defaults missing Discord connection presentation settings", () => {
  assert.equal(discordSuppressUrlPreviewsFromConfiguration(null), true);
  assert.equal(
    discordSuppressUrlPreviewsFromConfiguration({
      thread_auto_archive_duration_minutes: 1440,
    }),
    true,
  );
  assert.equal(discordThreadAutoArchiveDurationFromConfiguration(null), 1440);
});

void test("reads explicit Discord URL preview policy values", () => {
  assert.equal(
    discordSuppressUrlPreviewsFromConfiguration({
      suppress_url_previews: false,
    }),
    false,
  );
  assert.equal(
    discordSuppressUrlPreviewsFromConfiguration({
      suppress_url_previews: true,
    }),
    true,
  );
});
