import { readFileSync } from "node:fs";
import { createContext, Script } from "node:vm";
import ts from "typescript";
import type { Context } from "node:vm";

export function object(value: unknown): Record<string, unknown> {
  if (value == null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Expected a test observation object.");
  }
  return Object.fromEntries(Object.entries(value));
}
export function invoke(value: unknown, ...args: unknown[]): unknown {
  if (typeof value !== "function") {
    throw new Error("Expected a test boundary function.");
  }
  const result: unknown = Reflect.apply(value, null, args);
  return result;
}
export interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}
export interface NativeDeferred {
  promise: PromiseLike<unknown>;
  resolve: (value: unknown) => void;
}
function promiseLike(value: unknown): value is PromiseLike<unknown> {
  return (
    value != null &&
    typeof value === "object" &&
    "then" in value &&
    typeof value.then === "function"
  );
}
export function deferred<T>(): Deferred<T> {
  let resolve: ((value: T) => void) | null = null;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return {
    promise,
    resolve: (value) => {
      if (resolve == null) {
        throw new Error("Deferred was not initialized.");
      }
      resolve(value);
    },
  };
}
interface Effect {
  effect: () => unknown;
  deps: readonly unknown[] | null;
  cleanup: unknown;
  changed: boolean;
}
class FixtureDate extends Date {
  static now(): number {
    return Date.parse("2026-10-14T00:00:00Z");
  }
}
/** Execute production hook source with explicit React and external-I/O boundaries. No source substring assertions. */
export class HookHarness {
  private stateIndex = 0;
  private refIndex = 0;
  private effectIndex = 0;
  private states: unknown[] = [];
  private refs: Array<{ current: unknown }> = [];
  private effects: Effect[] = [];
  private hook: unknown;
  private props: unknown;
  private rendered: unknown;
  private sandbox: Context | null = null;
  readonly react = {
    useState: (initial: unknown): [unknown, (next: unknown) => void] => {
      const index = this.stateIndex++;
      if (!(index in this.states)) {
        this.states[index] =
          typeof initial === "function" ? invoke(initial) : initial;
      }
      return [
        this.states[index],
        (next) => {
          this.states[index] =
            typeof next === "function"
              ? invoke(next, this.states[index])
              : next;
        },
      ];
    },
    useRef: (initial: unknown): { current: unknown } => {
      const index = this.refIndex++;
      const current = this.refs[index];
      if (current != null) {
        return current;
      }
      const created = { current: initial };
      this.refs[index] = created;
      return created;
    },
    useEffect: (effect: () => unknown, deps?: readonly unknown[]): void => {
      const index = this.effectIndex++;
      const previous = this.effects[index];
      const changed =
        previous == null ||
        deps == null ||
        previous.deps == null ||
        deps.length !== previous.deps.length ||
        deps.some((value, item) => !Object.is(value, previous.deps?.[item]));
      this.effects[index] = {
        effect,
        deps: deps ?? null,
        cleanup: previous?.cleanup,
        changed,
      };
    },
    useLayoutEffect: (
      effect: () => unknown,
      deps?: readonly unknown[],
    ): void => {
      this.react.useEffect(effect, deps);
    },
    useCallback: (callback: unknown): unknown => callback,
    useMemo: (factory: () => unknown): unknown => factory(),
  };
  load(
    path: URL,
    exportName: string,
    modules: Record<string, unknown>,
    window: unknown,
    document?: unknown,
  ): unknown {
    const exports: Record<string, unknown> = {};
    const cjsModule = { exports };
    const source = ts.transpileModule(readFileSync(path, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText;
    this.sandbox = createContext({
      module: cjsModule,
      exports,
      require: (name: string): unknown => {
        if (!Object.hasOwn(modules, name)) {
          throw new Error(`Missing explicit hook test boundary: ${name}`);
        }
        return modules[name];
      },
      window,
      document,
      Promise,
      Date: FixtureDate,
    });
    new Script(source, { filename: path.pathname }).runInContext(this.sandbox);
    this.hook = cjsModule.exports[exportName];
    return this.hook;
  }
  nativeDeferred(): NativeDeferred {
    if (this.sandbox == null) {
      throw new Error("Load the hook before creating its I/O boundary.");
    }
    // Async functions use their realm's intrinsic Promise; the mock receipt uses that same realm.
    const receipt: unknown = new Script(`(() => {
      const NativePromise = (async () => {})().constructor;
      let resolve;
      const promise = new NativePromise(done => {resolve = done;});
      return {promise, resolve};
    })()`).runInContext(this.sandbox);
    const data = object(receipt);
    if (!promiseLike(data.promise)) {
      throw new Error("Expected a native provider receipt Promise.");
    }
    return {
      promise: data.promise,
      resolve: (value) => {
        invoke(data.resolve, value);
      },
    };
  }
  render(props?: unknown): Record<string, unknown> {
    if (props != null) {
      this.props = props;
    }
    this.stateIndex = 0;
    this.refIndex = 0;
    this.effectIndex = 0;
    this.rendered = invoke(this.hook, this.props);
    return object(this.rendered);
  }
  flushEffects(): void {
    for (const effect of this.effects) {
      if (!effect.changed) {
        continue;
      }
      if (typeof effect.cleanup === "function") {
        invoke(effect.cleanup);
      }
      effect.cleanup = effect.effect();
      effect.changed = false;
    }
  }
  unmount(): void {
    for (const effect of this.effects) {
      if (typeof effect.cleanup === "function") {
        invoke(effect.cleanup);
      }
    }
  }
  probeEffects(): void {
    this.unmount();
    for (const effect of this.effects) {
      effect.cleanup = effect.effect();
      effect.changed = false;
    }
  }
}
export class BrowserStorageFixture {
  readonly key: string;
  constructor(key: string) {
    this.key = key;
  }
  value: unknown = null;
  readonly writes: unknown[] = [];
  readonly mantine = {
    readSessionStorageValue: (options: unknown): unknown => {
      const settings = object(options);
      if (settings.key !== this.key || this.value == null) {
        return null;
      }
      return invoke(settings.deserialize, JSON.stringify(this.value));
    },
    useSessionStorage: (): [unknown, (value: unknown) => void, () => void] => [
      this.value,
      this.save,
      this.clear,
    ],
    useWindowEvent: (): void => {},
    useReducedMotion: (): boolean => true,
  };
  private save = (value: unknown): void => {
    this.value = value;
    this.writes.push(value);
  };
  private clear = (): void => {
    this.value = null;
    this.writes.push(null);
  };
}
export function noMutation(): {
  isPending: boolean;
  variables: null;
  mutate: () => void;
  mutateAsync: () => Promise<unknown>;
} {
  return {
    isPending: false,
    variables: null,
    mutate: () => {},
    mutateAsync: () => Promise.resolve(null),
  };
}
