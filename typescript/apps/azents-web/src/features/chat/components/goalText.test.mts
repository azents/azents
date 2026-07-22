import assert from "node:assert/strict";
import test from "node:test";

import { normalizeGoalPreviewText } from "./goalText.ts";

void test("normalizes Goal Markdown into readable preview text", () => {
  assert.equal(
    normalizeGoalPreviewText(`
# Ship the **external channel** Goal

- [ ] Review \`SlackTransport\` [design](https://example.com/design)
- [x] Verify ~~legacy~~ fixtures
`),
    "Ship the external channel Goal Review SlackTransport design Verify legacy fixtures",
  );
});

void test("preserves text content while removing Markdown-only syntax", () => {
  assert.equal(
    normalizeGoalPreviewText(`
> ![Azents logo](https://example.com/logo.svg) **Review** the [release notes][notes].

\`\`\`ts
const complete = true;
\`\`\`

[notes]: https://example.com/release
`),
    "Azents logo Review the release notes. const complete = true;",
  );
});

void test("collapses all whitespace into one preview line", () => {
  assert.equal(
    normalizeGoalPreviewText("  Complete\n\n  the\tGoal  "),
    "Complete the Goal",
  );
});
