import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyTerminalOutputSequence,
  isTerminalProjectionConnectable,
  isTerminalProjectionReconnectable,
  reconcilePendingTerminalInput,
  resolveReplayAcknowledgement,
  shouldRestoreChatForTerminalProjection,
} from "./protocol.ts";

void test("connects ready, active, and ended Terminal projections", () => {
  assert.equal(isTerminalProjectionConnectable("ready"), true);
  assert.equal(isTerminalProjectionConnectable("active"), true);
  assert.equal(isTerminalProjectionConnectable("ended"), true);
  assert.equal(isTerminalProjectionConnectable("stopped"), false);
  assert.equal(isTerminalProjectionReconnectable("active"), true);
  assert.equal(isTerminalProjectionReconnectable("ended"), false);
  assert.equal(shouldRestoreChatForTerminalProjection("unavailable"), true);
  assert.equal(shouldRestoreChatForTerminalProjection("absent"), true);
  assert.equal(shouldRestoreChatForTerminalProjection("active"), false);
});

void test("reconciles and resends only contiguous unaccepted input", () => {
  const pending = new Map<number, Uint8Array>([
    [4, new Uint8Array([4])],
    [5, new Uint8Array([5])],
    [6, new Uint8Array([6])],
  ]);
  const result = reconcilePendingTerminalInput(pending, 5);
  assert.equal(result.nextSequence, 7);
  assert.deepEqual(
    result.resend.map((item) => item.sequence),
    [5, 6],
  );
  assert.throws(() =>
    reconcilePendingTerminalInput(new Map([[6, new Uint8Array([6])]]), 5),
  );
});

void test("rejects output gaps and acknowledges replay only after rendering", () => {
  assert.equal(classifyTerminalOutputSequence(8, 8), "duplicate");
  assert.equal(classifyTerminalOutputSequence(8, 9), "next");
  assert.throws(() => classifyTerminalOutputSequence(8, 10));
  assert.equal(
    resolveReplayAcknowledgement({
      replayEnded: true,
      replayMaximumSequence: 12,
      highestRenderedSequence: 11,
    }),
    null,
  );
  assert.equal(
    resolveReplayAcknowledgement({
      replayEnded: true,
      replayMaximumSequence: 12,
      highestRenderedSequence: 12,
    }),
    12,
  );
});
