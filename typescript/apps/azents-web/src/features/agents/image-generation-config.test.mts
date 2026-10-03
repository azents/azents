import assert from "node:assert/strict";
import test from "node:test";
import {
  builtinToolConfigHasSettings,
  encodeImageGenerationModel,
  projectImageGenerationConfig,
} from "./image-generation-config.ts";

void test("opaque config compatibility metadata is validated at ingress", () => {
  assert.equal(builtinToolConfigHasSettings({}), false);
  assert.equal(builtinToolConfigHasSettings({ arbitrary: null }), true);
  assert.throws(() => builtinToolConfigHasSettings([]));
});

void test("image config projection preserves exact nonblank intent and historical defaults", () => {
  assert.deepEqual(projectImageGenerationConfig({ model: " image-model " }), {
    model: " image-model ",
  });
  for (const value of [
    void 0,
    null,
    {},
    { model: "" },
    { model: "   " },
    { model: 7 },
    { model: false },
  ]) {
    assert.deepEqual(projectImageGenerationConfig(value), { model: null });
  }
});

void test("image config egress changes only model and preserves opaque fields and identity", () => {
  const extension = { quality: ["high", 2], provider_flag: null };
  const raw = { model: "old", quality: "high", extension };
  const changed = encodeImageGenerationModel(raw, "new");
  assert.deepEqual(changed, { model: "new", quality: "high", extension });
  assert.equal(changed.extension, extension);
  assert.deepEqual(raw, { model: "old", quality: "high", extension });
  const cleared = encodeImageGenerationModel(raw, null);
  assert.deepEqual(cleared, { quality: "high", extension });
  assert.equal(cleared.extension, extension);
  assert.deepEqual(encodeImageGenerationModel(null, "new"), {
    model: "new",
  });
});
