import assert from "node:assert/strict";
import test from "node:test";

import { resolveSubagentNavigation } from "./subagentNavigation.ts";

const root = {
  session_agent_id: "root-agent",
  agent_session_id: "root-session",
  parent_session_agent_id: null,
  name: "Root",
  path: "/",
};

void test("resolves nested current, parent, and root navigation links", () => {
  const child = {
    session_agent_id: "child-agent",
    agent_session_id: "child-session",
    parent_session_agent_id: root.session_agent_id,
    name: "Child",
    path: "/child",
  };
  const grandchild = {
    session_agent_id: "grandchild-agent",
    agent_session_id: "grandchild-session",
    parent_session_agent_id: child.session_agent_id,
    name: "Grandchild",
    path: "/child/grandchild",
  };

  const navigation = resolveSubagentNavigation({
    nodes: [{ ...root, children: [{ ...child, children: [grandchild] }] }],
    current_session_agent_id: grandchild.session_agent_id,
    root_session_agent_id: root.session_agent_id,
  });

  assert.ok(navigation);
  assert.equal(navigation.currentName, grandchild.name);
  assert.equal(navigation.currentPath, grandchild.path);
  assert.equal(navigation.parent.session_agent_id, child.session_agent_id);
  assert.equal(navigation.root.session_agent_id, root.session_agent_id);
});

void test("hides navigation for the root session or incomplete trees", () => {
  assert.equal(
    resolveSubagentNavigation({
      nodes: [root],
      current_session_agent_id: root.session_agent_id,
      root_session_agent_id: root.session_agent_id,
    }),
    null,
  );
  assert.equal(
    resolveSubagentNavigation({
      nodes: [root],
      current_session_agent_id: "missing-agent",
      root_session_agent_id: root.session_agent_id,
    }),
    null,
  );
});
