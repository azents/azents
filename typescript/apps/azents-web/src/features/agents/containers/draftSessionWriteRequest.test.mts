import assert from "node:assert/strict";
import test from "node:test";

import {
  clientRequestIdForDraftSessionWrite,
  draftSessionWriteKey,
  type DraftSessionWriteSemantics,
} from "./draftSessionWriteRequest.ts";

const base: DraftSessionWriteSemantics = {
  agentId: "agent-1",
  message: "hello",
  inferenceProfile: { model_target_label: "Primary", reasoning_effort: null },
  attachments: ["exchange://attachment-1"],
  existingProjectPaths: ["/workspace/agent/app"],
  setupActions: [
    {
      type: "create_git_worktree",
      source_project_path: "/workspace/agent/source",
      starting_ref: "refs/heads/main",
    },
  ],
};

void test("an exact failed draft write reuses its request ID", () => {
  const key = draftSessionWriteKey(base);
  let created = 0;
  const nextId = (): string => `new-${(created += 1)}`;

  assert.equal(
    clientRequestIdForDraftSessionWrite(
      { key, id: "failed-request" },
      key,
      nextId,
    ),
    "failed-request",
  );
  assert.equal(created, 0);
});

void test("changing any semantic payload field rotates the request ID", () => {
  const failedKey = draftSessionWriteKey(base);
  const variants: DraftSessionWriteSemantics[] = [
    { ...base, message: "changed" },
    { ...base, attachments: ["exchange://attachment-2"] },
    {
      ...base,
      inferenceProfile: {
        model_target_label: "Primary",
        reasoning_effort: "high",
      },
    },
    { ...base, existingProjectPaths: ["/workspace/agent/other"] },
    { ...base, setupActions: [] },
  ];
  let created = 0;
  const nextId = (): string => `new-${(created += 1)}`;

  for (const variant of variants) {
    const nextKey = draftSessionWriteKey(variant);
    assert.notEqual(nextKey, failedKey);
    assert.match(
      clientRequestIdForDraftSessionWrite(
        { key: failedKey, id: "failed-request" },
        nextKey,
        nextId,
      ),
      /^new-/,
    );
  }
  assert.equal(created, variants.length);
});
