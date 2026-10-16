import assert from "node:assert/strict";
import test from "node:test";
import { HookHarness, invoke } from "../../shared/testing/hook-test-harness.ts";

void test("Runtime status owns its ready timeout and cancels it on lifecycle changes", () => {
  const h = new HookHarness();
  let timeout: (() => void) | null = null;
  const cleared: unknown[] = [];
  h.load(
    new URL("./containers/useRuntimeStatusIndicator.ts", import.meta.url),
    "useRuntimeStatusIndicator",
    { react: h.react },
    {
      setTimeout: (callback: () => void, delay: number): number => {
        assert.equal(delay, 3000);
        timeout = callback;
        return 7;
      },
      clearTimeout: (id: unknown): void => {
        cleared.push(id);
      },
    },
  );
  assert.equal(h.render({ status: "ready" }).visible, false);
  h.flushEffects();
  assert.equal(h.render().visible, true);
  invoke(timeout);
  assert.equal(h.render().visible, false);
  h.render({ status: "initializing" });
  h.flushEffects();
  assert.equal(h.render().visible, true);
  assert.deepEqual(cleared, [7]);
  h.unmount();
});

void test("Goal editor keeps callback outcome authoritative without elapsed waits", async () => {
  const h = new HookHarness();
  h.load(
    new URL("./containers/useTodoPreviewBar.ts", import.meta.url),
    "useGoalSection",
    { react: h.react },
    {},
  );
  const pending = h.nativeDeferred();
  const updates: unknown[] = [];
  let view = h.render({
    goal: { objective: "Current goal", status: "active" },
    onUpdateGoal: (value: unknown): PromiseLike<unknown> => {
      updates.push(value);
      return pending.promise;
    },
  });
  invoke(view.setEditing, true);
  invoke(view.setDraft, "  Verified goal  ");
  view = h.render();
  invoke(view.saveGoal);
  view = h.render();
  assert.equal(view.submitting, true);
  assert.equal(view.editing, true);
  assert.deepEqual(updates, ["Verified goal"]);
  pending.resolve(true);
  await pending.promise;
  view = h.render();
  assert.equal(view.submitting, false);
  assert.equal(view.editing, false);
});

void test("Goal confirmation retains hint and closes only after successful callback", async () => {
  const h = new HookHarness();
  h.load(
    new URL("./containers/useTodoPreviewBar.ts", import.meta.url),
    "useGoalSection",
    { react: h.react },
    {},
  );
  const pending = h.nativeDeferred();
  const hints: unknown[] = [];
  let view = h.render({
    goal: { objective: "Current goal", status: "paused" },
    onResumeGoal: (hint: unknown): PromiseLike<unknown> => {
      hints.push(hint);
      return pending.promise;
    },
  });
  invoke(view.setConfirmAction, "resume");
  invoke(view.setResumeHint, "Use verified sources");
  view = h.render();
  invoke(view.confirmGoalAction);
  assert.equal(h.render().submitting, true);
  pending.resolve(true);
  await pending.promise;
  view = h.render();
  assert.equal(view.confirmAction, null);
  assert.equal(view.resumeHint, "");
  assert.deepEqual(hints, ["Use verified sources"]);
});

void test("Todo disclosure and expanded items are independent per container", () => {
  const h = new HookHarness();
  h.load(
    new URL("./containers/useTodoPreviewBar.ts", import.meta.url),
    "useTodoPreviewBar",
    { react: h.react },
    {},
  );
  let view = h.render({ goal: null, isMobile: false, todo: { items: [] } });
  const initialItems = view.expandedItems;
  invoke(view.setOpened, true);
  invoke(view.toggleExpanded, "first");
  view = h.render();
  assert.equal(view.opened, true);
  assert.notEqual(view.expandedItems, initialItems);
});

void test("Retry countdown owns only a live pending deadline and releases its timer", () => {
  const h = new HookHarness();
  const cleared: unknown[] = [];
  const intervals: unknown[] = [];
  h.load(
    new URL("./containers/useRunRetryCard.ts", import.meta.url),
    "useRunRetryCard",
    { react: h.react, "@mantine/hooks": {} },
    {
      setInterval: (_callback: () => void, delay: number): number => {
        intervals.push(delay);
        return 9;
      },
      clearInterval: (id: unknown): void => {
        cleared.push(id);
      },
    },
  );
  let view = h.render({
    variant: "live",
    retry: { nextRetryAt: "2026-10-14T00:00:03Z" },
  });
  assert.equal(view.countdown, 3);
  h.flushEffects();
  assert.deepEqual(intervals, [1000]);
  view = h.render({ variant: "terminal" });
  h.flushEffects();
  assert.equal(view.countdown, null);
  assert.deepEqual(cleared, [9]);
});

void test("Attachment strip hook owns drag threshold and consumes only its next click", () => {
  const h = new HookHarness();
  h.load(
    new URL("./containers/useFileAttachmentList.ts", import.meta.url),
    "useAttachmentStrip",
    {
      react: h.react,
      "@mantine/core": { rem: (value: number): string => `${value / 16}rem` },
      "@mantine/hooks": {},
      "../fileAttachmentPresentation": {},
    },
    {},
  );
  const view = h.render({ files: [], onPreview: (): void => {} });
  let prevented = 0;
  let stopped = 0;
  const click = {
    preventDefault: (): void => {
      prevented += 1;
    },
    stopPropagation: (): void => {
      stopped += 1;
    },
  };
  invoke(view.onPointerDown, { clientX: 10 });
  invoke(view.onPointerMove, { clientX: 16 });
  invoke(view.onPointerUp);
  invoke(view.onClickCapture, click);
  assert.equal(prevented, 0);
  invoke(view.onPointerDown, { clientX: 10 });
  invoke(view.onPointerMove, { clientX: 17 });
  invoke(view.onPointerUp);
  invoke(view.onClickCapture, click);
  assert.equal(prevented, 1);
  assert.equal(stopped, 1);
  invoke(view.onClickCapture, click);
  assert.equal(prevented, 1);
});
