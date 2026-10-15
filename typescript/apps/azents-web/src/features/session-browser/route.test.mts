import assert from "node:assert/strict";
import test from "node:test";
import {
  browserPanelHref,
  browserToolTarget,
  isBrowserSessionPath,
  parseBrowserTarget,
} from "./route.ts";

const target = {
  task_id: "task",
  page_id: "page",
  resource_incarnation: "generation",
};
void test("Browser result links only target a concrete current Session route", () => {
  assert.equal(
    isBrowserSessionPath("/w/team/agents/agent/sessions/session"),
    true,
  );
  assert.equal(isBrowserSessionPath("/w/team/agents/agent"), false);
  assert.equal(
    isBrowserSessionPath("/w/team/agents/agent/sessions/session/other"),
    false,
  );
});
void test("Browser links retain concrete Session and use distinct target keys", () => {
  const href = browserPanelHref(
    "/w/team/agents/agent/sessions/session",
    "taskId=schedule&edit=1&other=value",
    target,
  );
  assert.equal(
    href,
    "/w/team/agents/agent/sessions/session?other=value&page=browser&browserTaskId=task&browserPageId=page&browserIncarnation=generation",
  );
  assert.deepEqual(parseBrowserTarget(href.split("?")[1] ?? ""), {
    type: "TARGET",
    target,
  });
});
void test("incomplete, empty and duplicate targets never silently choose another page", () => {
  assert.deepEqual(parseBrowserTarget(""), { type: "NONE" });
  for (const query of [
    "browserTaskId=task",
    "browserTaskId=&browserPageId=page&browserIncarnation=g",
    "browserTaskId=a&browserTaskId=b&browserPageId=p&browserIncarnation=g",
  ]) {
    assert.deepEqual(parseBrowserTarget(query), { type: "INVALID" });
  }
});
void test("only explicit page projections from Browser results create links", () => {
  assert.deepEqual(
    browserToolTarget(
      "browser_open",
      JSON.stringify({
        page: {
          id: "page",
          task_id: "task",
          resource_incarnation: "generation",
        },
      }),
    ),
    target,
  );
  assert.equal(
    browserToolTarget("other", JSON.stringify({ page: target })),
    null,
  );
  assert.equal(browserToolTarget("browser_open", '{"page":null}'), null);
  assert.equal(browserToolTarget("browser_open", "not JSON"), null);
});
