import assert from "node:assert/strict";
import test from "node:test";

import { normalizeMarkdownToPlainText } from "./markdown.ts";

void test("normalizes Markdown into readable plain text", () => {
  assert.equal(
    normalizeMarkdownToPlainText(`
# Ship the **external channel** Goal

- [ ] Review \`SlackTransport\` [design](https://example.com/design)
- [x] Verify ~~legacy~~ fixtures
`),
    "Ship the external channel Goal Review SlackTransport design Verify legacy fixtures",
  );
});

void test("preserves text content while removing Markdown-only syntax", () => {
  assert.equal(
    normalizeMarkdownToPlainText(`
> ![Azents logo](https://example.com/logo.svg) **Review** the [release notes][notes].

\`\`\`ts
const complete = true;
\`\`\`

[notes]: https://example.com/release
`),
    "Azents logo Review the release notes. const complete = true;",
  );
});

void test("collapses all whitespace into one plain-text line", () => {
  assert.equal(
    normalizeMarkdownToPlainText("  Complete\n\n  the\tGoal  "),
    "Complete the Goal",
  );
});
