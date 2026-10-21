import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createContext, Script } from "node:vm";
import ts from "typescript";

void test("final CTA emits its existing identity and destination once per click", () => {
  const calls: unknown[] = [];
  const exports: Record<string, unknown> = {};
  const sandbox = createContext({
    exports,
    require: (name: string): unknown => {
      if (name === "@/shared/lib/analytics") {
        return { trackCtaClick: (event: unknown) => calls.push(event) };
      }
      if (name === "@/shared/lib/links") {
        return { SITE_LINKS: { github: "https://github.com/azents/azents" } };
      }
      throw new Error(`Unexpected collaborator: ${name}`);
    },
  });
  new Script(
    ts.transpileModule(
      readFileSync(new URL("./useCtaSection.ts", import.meta.url), "utf8"),
      {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          target: ts.ScriptTarget.ES2022,
        },
      },
    ).outputText,
  ).runInContext(sandbox);
  const hook = exports.useCtaSection;
  if (typeof hook !== "function") {
    throw new Error("Expected the production CTA hook.");
  }
  const view: unknown = Reflect.apply(hook, null, []);
  if (view === null || typeof view !== "object" || !("onGithub" in view)) {
    throw new Error("Expected the CTA callback contract.");
  }
  if (typeof view.onGithub !== "function") {
    throw new Error("Expected the CTA callback.");
  }
  assert.equal(calls.length, 0);
  Reflect.apply(view.onGithub, null, []);
  assert.equal(calls.length, 1);
  assert.equal(
    JSON.stringify(calls[0]),
    JSON.stringify({
      ctaId: "final_cta_github",
      ctaLocation: "final_cta",
      destinationUrl: "https://github.com/azents/azents",
    }),
  );
});
