import { readFileSync } from "node:fs";
import { Script } from "node:vm";
import ts from "typescript";

export function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
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

interface Effect {
  callback: () => unknown;
  dependencies: readonly unknown[] | null;
  pending: boolean;
}

/** Execute actual hook source with explicit React and I/O collaborators. */
export class HookHarness {
  private stateIndex = 0;
  private effectIndex = 0;
  private refIndex = 0;
  private states: unknown[] = [];
  private refs: Array<{ current: unknown }> = [];
  private effects: Effect[] = [];
  private target: unknown;

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
      const existing = this.refs[index];
      if (existing != null) {
        return existing;
      }
      const created = { current: initial };
      this.refs[index] = created;
      return created;
    },
    useMemo: (factory: () => unknown): unknown => factory(),
    useCallback: (callback: unknown): unknown => callback,
    useEffect: (
      callback: () => unknown,
      dependencies?: readonly unknown[],
    ): void => {
      const index = this.effectIndex++;
      const previous = this.effects[index];
      const pending =
        previous == null ||
        dependencies == null ||
        previous.dependencies == null ||
        dependencies.length !== previous.dependencies.length ||
        dependencies.some(
          (value, item) => !Object.is(value, previous.dependencies?.[item]),
        );
      this.effects[index] = {
        callback,
        dependencies: dependencies ?? null,
        pending,
      };
    },
    createContext: (
      initial: unknown,
    ): { Provider: string; initial: unknown } => ({
      Provider: "ContextProvider",
      initial,
    }),
    useContext: (context: unknown): unknown => record(context).initial,
  };

  load(
    path: URL,
    exportName: string,
    modules: Record<string, unknown>,
    globals?: Record<string, unknown>,
  ): void {
    const exports: Record<string, unknown> = {};
    const cjsModule = { exports };
    const source = ts.transpileModule(readFileSync(path, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Script(source, { filename: path.pathname }).runInNewContext({
      module: cjsModule,
      exports,
      require: (name: string): unknown => {
        if (!Object.hasOwn(modules, name)) {
          throw new Error(`Missing explicit test boundary: ${name}`);
        }
        return modules[name];
      },
      ...globals,
    });
    this.target = cjsModule.exports[exportName];
  }

  render(props?: unknown): Record<string, unknown> {
    this.stateIndex = 0;
    this.refIndex = 0;
    this.effectIndex = 0;
    return record(invoke(this.target, props));
  }

  flushEffects(): void {
    for (const effect of this.effects) {
      if (effect.pending) {
        effect.pending = false;
        effect.callback();
      }
    }
  }
}
