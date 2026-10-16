import assert from "node:assert/strict";
import test from "node:test";
import { HookHarness, invoke } from "../../shared/testing/hook-test-harness.ts";

void test("editor presentation container preserves native paste activation and focus fence", () => {
  const h = new HookHarness();
  const receiver = { isConnected: true, value: "initial" };
  const insertions: unknown[] = [];
  const document = {
    activeElement: receiver,
    execCommand: (command: string, show: boolean, text: string): boolean => {
      insertions.push([command, show, text]);
      receiver.value = text;
      return true;
    },
  };
  const actions: unknown[] = [];
  const touch: unknown[] = [];
  h.load(
    new URL("./containers/useBrowserFieldEditorView.ts", import.meta.url),
    "useBrowserFieldEditorView",
    {
      react: h.react,
      "./useBrowserFieldEditorTransition": {
        useBrowserFieldEditorTransition: (draft: unknown): unknown => ({
          draft,
          duration: 0,
          exitDuration: 0,
          onExited: (): void => {},
        }),
      },
      "./useBrowserToolbarTouch": {
        useBrowserToolbarTouch: (callback: unknown): unknown => {
          touch.push(callback);
          return (): void => {};
        },
      },
    },
    {},
    document,
  );
  const controls = {
    draft: { kind: "text" },
    onCancel: (): void => {},
    onConfirm: (): void => {},
    onPaste: (insert: unknown): void => {
      actions.push(invoke(insert, "native text"));
    },
  };
  const view = h.render({ controls });
  const textRef = view.textRef;
  assert.ok(
    textRef !== null && typeof textRef === "object" && "current" in textRef,
  );
  textRef.current = receiver;
  invoke(view.activatePaste);
  assert.deepEqual(insertions, [["insertText", false, "native text"]]);
  assert.deepEqual(actions, ["native text"]);
  receiver.isConnected = false;
  invoke(view.activatePaste);
  assert.deepEqual(actions, ["native text", null]);
  assert.equal(insertions.length, 1);
  assert.equal(touch[0], controls.onCancel);
  assert.equal(touch[1], controls.onConfirm);
  assert.equal(touch[2], view.activatePaste);
});

void test("keyboard toolbar container wires independent paste and edit activation", () => {
  const h = new HookHarness();
  const observed: unknown[] = [];
  h.load(
    new URL("./containers/useBrowserKeyboardToolbar.ts", import.meta.url),
    "useBrowserKeyboardToolbar",
    {
      "./useBrowserToolbarTouch": {
        useBrowserToolbarTouch: (callback: unknown): unknown => {
          observed.push(callback);
          return callback;
        },
      },
    },
    {},
  );
  const onPaste = (): void => {};
  const onOpen = (): void => {};
  const result = h.render({
    onPaste,
    onOpen,
    viewport: null,
    appearance: "floating",
  });
  assert.deepEqual(observed, [onPaste, onOpen]);
  assert.equal(result.pasteRef, onPaste);
  assert.equal(result.openRef, onOpen);
});
