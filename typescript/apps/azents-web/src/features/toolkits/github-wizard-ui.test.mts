import assert from "node:assert/strict";
import test from "node:test";
import {
  wizardHeadingId,
  wizardScrollBehavior,
} from "../../shared/toolkits/github-wizard-progression.ts";
import {
  soleGitHubChoice,
  soleGitHubMethod,
} from "../../shared/toolkits/github-wizard-selection.ts";
import { gitHubWizardConnectionReady } from "../../shared/toolkits/github-wizard-state.ts";

void test("only complete actual one-choice lists auto-select; loading/error/multiple never do", () => {
  assert.equal(soleGitHubChoice("READY", ["7"]), "7");
  assert.equal(soleGitHubChoice("READY", []), null);
  assert.equal(soleGitHubChoice("READY", ["7", "8"]), null);
  assert.equal(soleGitHubChoice("LOADING", ["7"]), null);
  assert.equal(soleGitHubChoice("ERROR", ["7"]), null);
  assert.equal(soleGitHubChoice("READY", ["7"], true), null);
});
void test("App only auto-selects self-managed method for confirmed unavailable Platform; identity still explicit", () => {
  const absent = {
    type: "READY",
    userAccount: "absent",
    installation: "absent",
    callbackUrl: null,
  } as const;
  assert.equal(soleGitHubMethod(null, absent), null);
  assert.equal(soleGitHubMethod("PERSONAL", absent), null);
  assert.equal(soleGitHubMethod("APP", absent), "github_app");
  assert.equal(
    soleGitHubMethod("APP", { ...absent, installation: "incomplete" }),
    "github_app",
  );
  assert.equal(
    soleGitHubMethod("APP", { ...absent, installation: "configured" }),
    null,
  );
  assert.equal(soleGitHubMethod("APP", { type: "LOADING" }), null);
  assert.equal(soleGitHubMethod("APP", { type: "ERROR" }), null);
});
void test("progression has stable landmark IDs and honors reduced motion", () => {
  assert.equal(wizardHeadingId("METHOD"), "github-wizard-method");
  assert.equal(wizardHeadingId("REVIEW"), "github-wizard-review");
  assert.equal(wizardScrollBehavior(true), "auto");
  assert.equal(wizardScrollBehavior(false), "smooth");
});
void test("connection completion follows actual transport evidence, not downstream settings", () => {
  const verified = {
    type: "VERIFIED",
    transport: "CURRENT",
    verification: {
      identity: {
        type: "user",
        id: 42,
        login: "fixture-user",
        avatar_url: null,
      },
      installations: [],
      connectivity: { status: "ready", message: null },
    },
  } as const;
  const mutable = {
    ...verified,
    verification: { ...verified.verification, installations: [] },
  };
  assert.equal(gitHubWizardConnectionReady(mutable), true);
  assert.equal(
    gitHubWizardConnectionReady({ ...mutable, transport: "STALE" }),
    false,
  );
  assert.equal(
    gitHubWizardConnectionReady({ ...mutable, transport: "CHECKING" }),
    false,
  );
  assert.equal(gitHubWizardConnectionReady({ type: "INPUT" }), false);
});
