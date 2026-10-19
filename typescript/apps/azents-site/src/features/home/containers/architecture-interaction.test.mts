import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createContext, Script } from "node:vm";
import ts from "typescript";

function fixture(): {
  run: () => Record<string, unknown>;
  setTime: (time: number) => void;
  calls: unknown[];
} {
  let now = 1000;
  let index = 0;
  const refs: Array<{ current: unknown }> = [];
  let refIndex = 0;
  const exports: Record<string, unknown> = {};
  const sandbox = createContext({
    exports,
    require: (name: string): unknown => {
      assert.equal(name, "react");
      return {
        useRef: (value: unknown) =>
          refs[refIndex++] ?? (refs[refIndex - 1] = { current: value }),
        useState: () => [
          index,
          (next: number) => {
            index = next;
          },
        ],
      };
    },
    Date: { now: () => now },
  });
  const code = ts.transpileModule(
    readFileSync(
      new URL("./useArchitectureDeepDive.ts", import.meta.url),
      "utf8",
    ),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText;
  new Script(code).runInContext(sandbox);
  const hook = exports.useArchitectureDeepDive;
  assert.equal(typeof hook, "function");
  if (typeof hook !== "function") {
    throw new Error("Missing interaction hook");
  }
  return {
    run: () => {
      refIndex = 0;
      const result: unknown = Reflect.apply(hook, null, [{ slideCount: 3 }]);
      if (
        result === null ||
        typeof result !== "object" ||
        Array.isArray(result)
      ) {
        throw new Error("Expected interaction state");
      }
      return Object.fromEntries(Object.entries(result));
    },
    setTime: (time) => {
      now = time;
    },
    calls: [],
  };
}
function call(value: unknown, ...args: unknown[]): void {
  if (typeof value !== "function") {
    throw new Error("Missing callback");
  }
  Reflect.apply(value, null, args);
}
void test("architecture keyboard and wheel preserve native receipt, threshold and 420ms throttle", () => {
  const f = fixture();
  let view = f.run();
  const calls: unknown[] = [];
  const event = (key: string): object => ({
    key,
    preventDefault: () => calls.push("prevent"),
  });
  call(view.handleKeyDown, event("End"));
  assert.equal(calls.length, 0);
  call(view.getEmblaApi, {
    scrollPrev: () => calls.push("prev"),
    scrollNext: () => calls.push("next"),
    scrollTo: (i: number) => calls.push(i),
  });
  for (const key of ["ArrowLeft", "ArrowRight", "Home", "End", "Other"]) {
    call(view.handleKeyDown, event(key));
  }
  assert.deepEqual(calls, [
    "prevent",
    "prev",
    "prevent",
    "next",
    "prevent",
    0,
    "prevent",
    2,
  ]);
  calls.length = 0;
  const wheel = (x: number, y: number): object => ({
    deltaX: x,
    deltaY: y,
    preventDefault: () => calls.push("prevent"),
  });
  call(view.handleWheel, wheel(27, 0));
  assert.equal(calls.length, 0);
  call(view.handleWheel, wheel(28, 0));
  f.setTime(1419);
  call(view.handleWheel, wheel(0, -30));
  f.setTime(1420);
  call(view.handleWheel, wheel(0, -30));
  assert.deepEqual(calls, ["prevent", "next", "prevent", "prevent", "prev"]);
  call(view.onSlideChange, 2);
  view = f.run();
  assert.equal(view.activeIndex, 2);
});
