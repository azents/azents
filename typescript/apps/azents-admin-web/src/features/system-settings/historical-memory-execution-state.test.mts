import assert from "node:assert/strict";
import test from "node:test";
import {
  editHistoricalMemoryExecutionForm,
  historicalMemoryExecutionConflict,
  historicalMemoryExecutionDirty,
  historicalMemoryExecutionDraft,
  historicalMemoryExecutionSaveInput,
  historicalMemoryExecutionValues,
  loadHistoricalMemoryExecutionForm,
  receiveHistoricalMemoryExecutionDetail,
} from "./historical-memory-execution-state.ts";

const detail = {
  section: "historical-memory-execution",
  schema_version: 1,
  admin_version: 3,
  max_turns: null,
  timeout_seconds: 600,
};

await test("unlimited turns render blank with the effective 600 second timeout", () => {
  assert.deepEqual(historicalMemoryExecutionDraft(detail), {
    maxTurns: "",
    timeoutSeconds: 600,
  });
  assert.equal(
    historicalMemoryExecutionDirty(
      historicalMemoryExecutionDraft(detail),
      detail,
    ),
    false,
  );
});

await test("blank turns produce explicit null for a versioned save", () => {
  assert.deepEqual(
    historicalMemoryExecutionValues({ maxTurns: "", timeoutSeconds: 600 }),
    { type: "VALID", maxTurns: null, timeoutSeconds: 600 },
  );
});

await test("positive integer edits are valid and dirty", () => {
  const draft = { maxTurns: 12, timeoutSeconds: 900 };
  assert.deepEqual(historicalMemoryExecutionValues(draft), {
    type: "VALID",
    maxTurns: 12,
    timeoutSeconds: 900,
  });
  assert.equal(historicalMemoryExecutionDirty(draft, detail), true);
});

await test("clearing a configured turn limit is a real change", () => {
  assert.equal(
    historicalMemoryExecutionDirty(
      { maxTurns: "", timeoutSeconds: 600 },
      { ...detail, max_turns: 12 },
    ),
    true,
  );
});

await test("invalid integer or blank timeout values block a save", () => {
  for (const value of [0, -1, 1.5, Infinity, NaN, "12", "invalid"]) {
    assert.deepEqual(
      historicalMemoryExecutionValues({ maxTurns: value, timeoutSeconds: 600 }),
      { type: "INVALID" },
    );
  }
  for (const value of [0, -1, 1.5, Infinity, NaN, "", "600"]) {
    assert.deepEqual(
      historicalMemoryExecutionValues({ maxTurns: "", timeoutSeconds: value }),
      { type: "INVALID" },
    );
  }
});

await test("background vN+1 preserves dirty vN edits and its baseline", () => {
  const loaded = loadHistoricalMemoryExecutionForm(detail);
  const edited = editHistoricalMemoryExecutionForm(loaded, {
    maxTurns: 12,
    timeoutSeconds: 900,
  });
  const incoming = {
    ...detail,
    admin_version: 4,
    max_turns: 20,
    timeout_seconds: 1200,
  };
  const preserved = receiveHistoricalMemoryExecutionDetail(edited, incoming);
  assert.deepEqual(preserved.draft, edited.draft);
  assert.deepEqual(preserved.baseline, detail);
  assert.equal(preserved.newerVersion, 4);
  assert.equal(
    historicalMemoryExecutionDirty(preserved.draft, preserved.baseline),
    true,
  );
});

await test("save captures the loaded form version instead of the latest query version", () => {
  const edited = editHistoricalMemoryExecutionForm(
    loadHistoricalMemoryExecutionForm(detail),
    { maxTurns: 12, timeoutSeconds: 900 },
  );
  const submitted = historicalMemoryExecutionSaveInput(edited);
  const withNewerQuery = receiveHistoricalMemoryExecutionDetail(edited, {
    ...detail,
    admin_version: 4,
    timeout_seconds: 1200,
  });
  assert.deepEqual(submitted, {
    expectedVersion: 3,
    maxTurns: 12,
    timeoutSeconds: 900,
  });
  assert.deepEqual(
    historicalMemoryExecutionSaveInput(withNewerQuery),
    submitted,
  );
});

await test("explicit reload adopts latest settings and clears dirty/stale state", () => {
  const edited = editHistoricalMemoryExecutionForm(
    loadHistoricalMemoryExecutionForm(detail),
    { maxTurns: 12, timeoutSeconds: 900 },
  );
  const incoming = {
    ...detail,
    admin_version: 4,
    max_turns: 20,
    timeout_seconds: 1200,
  };
  const stale = receiveHistoricalMemoryExecutionDetail(edited, incoming);
  assert.equal(stale.newerVersion, 4);
  const reloaded = loadHistoricalMemoryExecutionForm(incoming);
  assert.equal(reloaded.newerVersion, null);
  assert.deepEqual(reloaded.draft, { maxTurns: 20, timeoutSeconds: 1200 });
  assert.equal(
    historicalMemoryExecutionDirty(reloaded.draft, reloaded.baseline),
    false,
  );
  assert.equal(
    historicalMemoryExecutionSaveInput(reloaded)?.expectedVersion,
    4,
  );
});

await test("own save success resets the draft and ignores an older refetch result", () => {
  const saved = {
    ...detail,
    admin_version: 4,
    max_turns: 12,
    timeout_seconds: 900,
  };
  const committed = loadHistoricalMemoryExecutionForm(saved);
  assert.deepEqual(committed.draft, { maxTurns: 12, timeoutSeconds: 900 });
  assert.equal(committed.newerVersion, null);
  assert.equal(
    historicalMemoryExecutionDirty(committed.draft, committed.baseline),
    false,
  );
  assert.equal(
    receiveHistoricalMemoryExecutionDetail(committed, detail),
    committed,
  );
});

await test("stale warning persists through background refetch until explicit reload", () => {
  const edited = editHistoricalMemoryExecutionForm(
    loadHistoricalMemoryExecutionForm(detail),
    { maxTurns: 12, timeoutSeconds: 900 },
  );
  const stale = receiveHistoricalMemoryExecutionDetail(edited, {
    ...detail,
    admin_version: 4,
  });
  const reverted = editHistoricalMemoryExecutionForm(
    stale,
    historicalMemoryExecutionDraft(detail),
  );
  const refreshed = receiveHistoricalMemoryExecutionDetail(reverted, {
    ...detail,
    admin_version: 5,
  });
  assert.equal(refreshed.baseline.admin_version, 3);
  assert.equal(refreshed.newerVersion, 5);
});

await test("clean forms may adopt a newer background version", () => {
  const incoming = { ...detail, admin_version: 4, timeout_seconds: 900 };
  const refreshed = receiveHistoricalMemoryExecutionDetail(
    loadHistoricalMemoryExecutionForm(detail),
    incoming,
  );
  assert.equal(refreshed.baseline.admin_version, 4);
  assert.deepEqual(refreshed.draft, { maxTurns: "", timeoutSeconds: 900 });
  assert.equal(refreshed.newerVersion, null);
});

await test("API 409 without newer query data blocks another save and preserves edits until reload succeeds", () => {
  const edited = editHistoricalMemoryExecutionForm(
    loadHistoricalMemoryExecutionForm(detail),
    { maxTurns: 12, timeoutSeconds: 900 },
  );
  assert.equal(edited.newerVersion, null);
  assert.equal(historicalMemoryExecutionConflict(edited, null), false);

  const after409 = receiveHistoricalMemoryExecutionDetail(edited, detail);
  assert.equal(after409.newerVersion, null);
  assert.equal(historicalMemoryExecutionConflict(after409, "CONFLICT"), true);
  assert.deepEqual(after409.draft, { maxTurns: 12, timeoutSeconds: 900 });
  assert.equal(after409.baseline.admin_version, 3);
  assert.equal(
    historicalMemoryExecutionSaveInput(after409)?.expectedVersion,
    3,
  );

  const furtherEdit = editHistoricalMemoryExecutionForm(after409, {
    maxTurns: 13,
    timeoutSeconds: 900,
  });
  assert.equal(
    historicalMemoryExecutionConflict(furtherEdit, "CONFLICT"),
    true,
  );
  assert.equal(
    historicalMemoryExecutionConflict(
      receiveHistoricalMemoryExecutionDetail(furtherEdit, detail),
      "CONFLICT",
    ),
    true,
  );

  const reloaded = loadHistoricalMemoryExecutionForm({
    ...detail,
    admin_version: 4,
    max_turns: 20,
    timeout_seconds: 1200,
  });
  assert.equal(historicalMemoryExecutionConflict(reloaded, null), false);
  assert.equal(reloaded.baseline.admin_version, 4);
  assert.deepEqual(reloaded.draft, { maxTurns: 20, timeoutSeconds: 1200 });
});

await test("failed reload retains the API 409 latch; only successful reload clears it", () => {
  const edited = editHistoricalMemoryExecutionForm(
    loadHistoricalMemoryExecutionForm(detail),
    { maxTurns: 12, timeoutSeconds: 900 },
  );
  const formAfterFailedFetch = receiveHistoricalMemoryExecutionDetail(
    edited,
    detail,
  );
  assert.equal(formAfterFailedFetch, edited);
  assert.equal(
    historicalMemoryExecutionConflict(formAfterFailedFetch, "CONFLICT"),
    true,
  );
  assert.deepEqual(formAfterFailedFetch.draft, edited.draft);
  assert.equal(formAfterFailedFetch.baseline.admin_version, 3);

  const formAfterSuccessfulFetch = loadHistoricalMemoryExecutionForm({
    ...detail,
    admin_version: 4,
    max_turns: 20,
  });
  assert.equal(
    historicalMemoryExecutionConflict(formAfterSuccessfulFetch, null),
    false,
  );
  assert.equal(formAfterSuccessfulFetch.baseline.admin_version, 4);
});
