import assert from "node:assert/strict";
import test from "node:test";
import {
  automaticProjectsBaseline,
  automaticProjectsEditingDisabled,
  automaticProjectsErrorProjection,
  automaticProjectsSaveEnabled,
  commitAutomaticProjectsReplacement,
  dedupeProjectPaths,
  deriveAutomaticProjectsState,
  fetchLatestAutomaticProjects,
  initializeAutomaticProjectsBaseline,
  normalizeProjectPath,
  projectBasename,
} from "./automaticProjects.ts";
import type { AutomaticProjectRow } from "./automaticProjects.ts";

const rows: AutomaticProjectRow[] = [
  {
    path: "/workspace/agent/demo",
    name: "demo",
    status: "available",
    detail: null,
  },
];

void test("normalizes paths without erasing the filesystem root", () => {
  assert.equal(
    normalizeProjectPath("/workspace/agent/demo///"),
    "/workspace/agent/demo",
  );
  assert.equal(normalizeProjectPath("/"), "/");
});

void test("deduplicates ordered project paths", () => {
  assert.deepEqual(
    dedupeProjectPaths([
      "/workspace/agent/demo/",
      "/workspace/agent/demo",
      "",
      "/workspace/agent/other",
    ]),
    ["/workspace/agent/demo", "/workspace/agent/other"],
  );
});

void test("derives a display basename", () => {
  assert.equal(projectBasename("/workspace/agent/payment-api"), "payment-api");
});

void test("maps policy query failures before loading state", () => {
  assert.deepEqual(
    deriveAutomaticProjectsState({
      policyLoading: false,
      policyLoaded: false,
      policyError: "Policy request failed.",
      draftInitialized: false,
      mutationPending: false,
      revision: 1,
      rows: [],
      updatedAt: "",
      dirty: false,
      saveError: null,
    }),
    { type: "ERROR", message: "Policy request failed." },
  );
});

void test("keeps draft rows for conflict and runtime recovery states", () => {
  const base = {
    policyLoading: false,
    policyLoaded: true,
    policyError: null,
    draftInitialized: true,
    mutationPending: false,
    revision: 2,
    rows,
    updatedAt: "2026-07-24T00:00:00Z",
    dirty: true,
  };
  assert.equal(
    deriveAutomaticProjectsState({
      ...base,
      saveError: {
        code: "automatic_session_projects_revision_conflict",
        message: "Conflict.",
        path: null,
      },
    }).type,
    "CONFLICT",
  );
  assert.equal(
    deriveAutomaticProjectsState({
      ...base,
      saveError: {
        code: "automatic_session_projects_runtime_unavailable",
        message: "Runtime unavailable.",
        path: null,
      },
    }).type,
    "RUNTIME_UNAVAILABLE",
  );
});

void test("maps invalid-path and generic save failures without losing rows", () => {
  const base = {
    policyLoading: false,
    policyLoaded: true,
    policyError: null,
    draftInitialized: true,
    mutationPending: false,
    revision: 2,
    rows,
    updatedAt: "2026-07-24T00:00:00Z",
    dirty: true,
  };
  assert.deepEqual(
    deriveAutomaticProjectsState({
      ...base,
      saveError: {
        code: "automatic_session_projects_invalid_path",
        message: "Path is not available.",
        path: "/workspace/agent/demo",
      },
    }),
    {
      type: "VALIDATION_ERROR",
      revision: 2,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
      message: "Path is not available.",
      path: "/workspace/agent/demo",
    },
  );
  assert.deepEqual(
    deriveAutomaticProjectsState({
      ...base,
      saveError: {
        code: null,
        message: "Request failed.",
        path: null,
      },
    }),
    {
      type: "EDITOR_ERROR",
      revision: 2,
      rows,
      updatedAt: "2026-07-24T00:00:00Z",
      message: "Request failed.",
    },
  );
});

void test("saving disables edits and save submission", () => {
  const saving = deriveAutomaticProjectsState({
    policyLoading: false,
    policyLoaded: true,
    policyError: null,
    draftInitialized: true,
    mutationPending: true,
    revision: 2,
    rows,
    updatedAt: "2026-07-24T00:00:00Z",
    dirty: true,
    saveError: null,
  });
  assert.equal(saving.type, "SAVING");
  assert.equal(automaticProjectsEditingDisabled(saving), true);
  assert.equal(automaticProjectsSaveEnabled(saving), false);
});

void test("keeps the draft-bound baseline during background policy refresh", () => {
  const initial = automaticProjectsBaseline({
    revision: 2,
    project_paths: ["/workspace/agent/demo/"],
    updated_at: "2026-07-24T00:00:00Z",
  });
  const retained = initializeAutomaticProjectsBaseline(initial, {
    revision: 3,
    project_paths: ["/workspace/agent/other"],
    updated_at: "2026-07-24T01:00:00Z",
  });
  assert.equal(retained, initial);
  assert.deepEqual(retained, {
    revision: 2,
    paths: ["/workspace/agent/demo"],
    updatedAt: "2026-07-24T00:00:00Z",
  });
});

void test("successful replacement adopts returned policy and invalidates queries", async () => {
  const calls: string[] = [];
  const response = {
    revision: 4,
    project_paths: ["/workspace/agent/other/", "/workspace/agent/demo"],
    updated_at: "2026-07-24T02:00:00Z",
  };
  const saved = await commitAutomaticProjectsReplacement({
    mutate: () => {
      calls.push("mutate");
      return Promise.resolve(response);
    },
    setPolicyData: (value) => {
      assert.equal(value, response);
      calls.push("set-data");
    },
    invalidatePolicy: () => {
      calls.push("invalidate-policy");
      return Promise.resolve();
    },
    invalidatePreview: () => {
      calls.push("invalidate-preview");
      return Promise.resolve();
    },
  });
  assert.deepEqual(saved, {
    revision: 4,
    paths: ["/workspace/agent/other", "/workspace/agent/demo"],
    updatedAt: "2026-07-24T02:00:00Z",
  });
  assert.deepEqual(calls, [
    "mutate",
    "set-data",
    "invalidate-policy",
    "invalidate-preview",
  ]);
});

void test("failed replacement does not adopt or invalidate policy state", async () => {
  const calls: string[] = [];
  await assert.rejects(
    commitAutomaticProjectsReplacement({
      mutate: () => Promise.reject(new Error("Conflict.")),
      setPolicyData: () => {
        calls.push("set-data");
      },
      invalidatePolicy: () => {
        calls.push("invalidate-policy");
        return Promise.resolve();
      },
      invalidatePreview: () => {
        calls.push("invalidate-preview");
        return Promise.resolve();
      },
    }),
    /Conflict/,
  );
  assert.deepEqual(calls, []);
});

void test("reload invalidates before fetching and adopts the latest policy", async () => {
  const calls: string[] = [];
  const latest = await fetchLatestAutomaticProjects({
    invalidatePolicy: () => {
      calls.push("invalidate");
      return Promise.resolve();
    },
    fetchPolicy: () => {
      calls.push("fetch");
      return Promise.resolve({
        revision: 5,
        project_paths: ["/workspace/agent/latest"],
        updated_at: "2026-07-24T03:00:00Z",
      });
    },
  });
  assert.deepEqual(calls, ["invalidate", "fetch"]);
  assert.deepEqual(latest, {
    revision: 5,
    paths: ["/workspace/agent/latest"],
    updatedAt: "2026-07-24T03:00:00Z",
  });
});

void test("reads only the bounded tRPC API error projection", () => {
  assert.deepEqual(
    automaticProjectsErrorProjection({
      data: {
        apiError: {
          code: "automatic_session_projects_invalid_path",
          message: "Invalid path.",
          path: "/workspace/agent/missing",
          ignored: "not projected",
        },
      },
    }),
    {
      code: "automatic_session_projects_invalid_path",
      message: "Invalid path.",
      path: "/workspace/agent/missing",
    },
  );
  assert.equal(automaticProjectsErrorProjection(new Error("Network")), null);
});

void test("keeps missing-path clean and dirty distinction", () => {
  const missingRows: AutomaticProjectRow[] = [
    {
      path: "/workspace/agent/demo",
      name: "demo",
      status: "missing",
      detail: null,
    },
  ];
  const input = {
    policyLoading: false,
    policyLoaded: true,
    policyError: null,
    draftInitialized: true,
    mutationPending: false,
    revision: 2,
    rows: missingRows,
    updatedAt: "2026-07-24T00:00:00Z",
    saveError: null,
  };
  assert.deepEqual(deriveAutomaticProjectsState({ ...input, dirty: false }), {
    type: "MISSING",
    revision: 2,
    rows: missingRows,
    updatedAt: "2026-07-24T00:00:00Z",
    message: "",
    dirty: false,
  });
  assert.deepEqual(deriveAutomaticProjectsState({ ...input, dirty: true }), {
    type: "MISSING",
    revision: 2,
    rows: missingRows,
    updatedAt: "2026-07-24T00:00:00Z",
    message: "",
    dirty: true,
  });
});
