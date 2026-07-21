import assert from "node:assert/strict";
import test from "node:test";
import {
  completedCompactionIds,
  isCompactionInProgressMarker,
} from "./compactionPresentation.ts";
import type { ChatMessage } from "./types.ts";

function compactionMessage(
  id: string,
  role: "compaction" | "compaction_started",
  compactionId: string | null,
): ChatMessage {
  return {
    id,
    role,
    content: null,
    createdAt: "2026-07-21T00:00:00Z",
    status: "complete",
    metadata: compactionId === null ? {} : { compaction_id: compactionId },
  };
}

void test("hides a completed compaction marker with the same compaction id", () => {
  const marker = compactionMessage(
    "marker-1",
    "compaction_started",
    "compaction-1",
  );
  const summary = compactionMessage("summary-1", "compaction", "compaction-1");

  const completedIds = completedCompactionIds([marker, summary]);

  assert.equal(isCompactionInProgressMarker(marker, completedIds), false);
});

void test("keeps an unmatched compaction marker visible", () => {
  const marker = compactionMessage(
    "marker-1",
    "compaction_started",
    "compaction-1",
  );
  const summary = compactionMessage("summary-2", "compaction", "compaction-2");

  const completedIds = completedCompactionIds([marker, summary]);

  assert.equal(isCompactionInProgressMarker(marker, completedIds), true);
});

void test("keeps a legacy compaction marker without an id visible", () => {
  const marker = compactionMessage("marker-1", "compaction_started", null);

  assert.equal(isCompactionInProgressMarker(marker, new Set()), true);
});
