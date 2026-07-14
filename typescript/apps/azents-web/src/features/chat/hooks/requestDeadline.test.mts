import assert from "node:assert/strict";
import test from "node:test";

import {
  type RequestDeadlineClock,
  RequestDeadlineExceededError,
  withRequestDeadline,
} from "./requestDeadline.ts";

interface ControlledDeadlineClock {
  clock: RequestDeadlineClock;
  fire: () => void;
  cancelled: () => boolean;
}

function controlledDeadlineClock(): ControlledDeadlineClock {
  let callback: (() => void) | null = null;
  let timerCancelled = false;
  const timer = setTimeout(() => {}, 60_000);
  clearTimeout(timer);
  return {
    clock: {
      schedule: (nextCallback) => {
        callback = nextCallback;
        return timer;
      },
      cancel: (scheduledTimer) => {
        assert.equal(scheduledTimer, timer);
        timerCancelled = true;
        clearTimeout(timer);
      },
    },
    fire: () => {
      assert.notEqual(callback, null);
      callback?.();
    },
    cancelled: () => timerCancelled,
  };
}

void test("a completed request cancels its deadline", async () => {
  const deadline = controlledDeadlineClock();

  assert.equal(
    await withRequestDeadline(Promise.resolve("complete"), 100, deadline.clock),
    "complete",
  );
  assert.equal(deadline.cancelled(), true);
});

void test("a hung request rejects at the caller deadline", async () => {
  const deadline = controlledDeadlineClock();
  const request = withRequestDeadline(
    new Promise<string>(() => {}),
    100,
    deadline.clock,
  );

  deadline.fire();

  await assert.rejects(request, RequestDeadlineExceededError);
});

void test("a late remote completion cannot overwrite the deadline result", async () => {
  const deadline = controlledDeadlineClock();
  let resolveRemote: (value: string) => void = () => {};
  const remote = new Promise<string>((resolve) => {
    resolveRemote = resolve;
  });
  const request = withRequestDeadline(remote, 100, deadline.clock);

  deadline.fire();
  resolveRemote("committed");

  await assert.rejects(request, RequestDeadlineExceededError);
});
