import assert from "node:assert/strict";
import test from "node:test";
import { formatLocalizedDate } from "./date-format.ts";

const timestamp = new Date("2026-07-21T12:05:00.000Z");
const timestampOptions = {
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  month: "short",
  timeZone: "UTC",
} satisfies Intl.DateTimeFormatOptions;

await test("formats dates with the selected account locale", () => {
  assert.match(
    formatLocalizedDate(timestamp, "en-US", timestampOptions),
    /Jul/,
  );
  assert.match(
    formatLocalizedDate(timestamp, "ko-KR", timestampOptions),
    /7월/,
  );
});
