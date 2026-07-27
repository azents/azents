import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

void test("touch form controls keep an iOS-safe font size", async () => {
  const stylesheet = await readFile(
    new URL("./globals.css", import.meta.url),
    "utf8",
  );
  const layout = await readFile(
    new URL("./layout.tsx", import.meta.url),
    "utf8",
  );

  assert.match(layout, /import "\.\/globals\.css";/);
  assert.match(stylesheet, /@media \(pointer: coarse\)/);
  assert.match(stylesheet, /\.azents-admin input/);
  assert.match(stylesheet, /\.azents-admin select/);
  assert.match(stylesheet, /\.azents-admin textarea/);
  assert.match(stylesheet, /font-size: max\(1rem, 16px\)/);
});
