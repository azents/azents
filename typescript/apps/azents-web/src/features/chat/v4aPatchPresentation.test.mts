import assert from "node:assert/strict";
import test from "node:test";
import { parseV4APatch } from "./v4aPatchPresentation.ts";

void test("parses strict V4A operations into file-specific diffs", () => {
  const patch = `*** Begin Patch
*** Update File: src/example.ts
*** Move to: src/renamed.ts
@@ function value()
 export const value = 1;
-export const label = "old";
+export const label = "new";
*** Add File: src/new.ts
+export const created = true;
*** Delete File: src/removed.ts
*** End Patch`;

  assert.deepEqual(parseV4APatch(patch), {
    files: [
      {
        type: "update",
        path: "src/example.ts",
        moveTo: "src/renamed.ts",
        hunks: [
          {
            context: "function value()",
            lines: [
              { type: "context", content: "export const value = 1;" },
              { type: "remove", content: 'export const label = "old";' },
              { type: "add", content: 'export const label = "new";' },
            ],
          },
        ],
      },
      {
        type: "add",
        path: "src/new.ts",
        lines: ["export const created = true;"],
      },
      { type: "delete", path: "src/removed.ts" },
    ],
  });
});

void test("rejects malformed V4A input", () => {
  assert.equal(
    parseV4APatch(
      "*** Begin Patch\n*** Update File: src/example.ts\n*** End Patch",
    ),
    null,
  );
});
