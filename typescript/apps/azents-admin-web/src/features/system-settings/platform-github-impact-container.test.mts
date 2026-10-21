import assert from "node:assert/strict";
import { test } from "node:test";
import { settingsSectionFromValue } from "../../shared/lib/admin-navigation.ts";
import {
  HookHarness,
  invoke,
  record,
} from "../../shared/testing/hook-harness.ts";
import * as impactProjection from "./platform-github-impact.ts";

function setup(impact: unknown): {
  harness: HookHarness;
  detail: Record<string, unknown>;
  confirmations: unknown[];
} {
  const harness = new HookHarness();
  const confirmations: unknown[] = [];
  const detail: Record<string, unknown> = {
    admin_version: 4,
    fields: [],
    candidate: { id: "candidate-1", impact, validation_status: "valid" },
  };
  const query = (data: unknown): unknown => ({
    data,
    isPending: false,
    isError: false,
    error: null,
  });
  const mutation = (capture?: unknown[]): unknown => ({
    useMutation: () => ({
      isPending: false,
      error: null,
      mutate: (input: unknown) => capture?.push(record(input)),
    }),
  });
  const settings = {
    getExternalChannelFiles: {
      useQuery: () =>
        query({
          outbound_max_file_bytes: 1024,
          outbound_max_action_bytes: 4096,
        }),
    },
    getPlatformGitHubApp: { useQuery: () => query(detail) },
    listAuditEvents: { useQuery: () => query({ items: [], total: 0 }) },
    patchExternalChannelFiles: mutation(),
    patchPlatformGitHubApp: mutation(),
    validatePlatformGitHubAppCandidate: mutation(),
    confirmPlatformGitHubAppCandidate: mutation(confirmations),
    cancelPlatformGitHubAppCandidate: mutation(),
    checkPlatformGitHubAppHealth: mutation(),
  };
  harness.load(
    new URL("./containers/useSystemSettingsPageContainer.ts", import.meta.url),
    "useSystemSettingsPageContainer",
    {
      react: harness.react,
      "../platform-github-impact": impactProjection,
      "@/trpc/client": {
        trpc: {
          useUtils: () => ({ systemSettings: {} }),
          systemSettings: settings,
        },
      },
    },
  );
  return { harness, detail, confirmations };
}

void test("section-only query navigation preserves the unsaved parent settings draft", () => {
  const { harness } = setup(null);
  let section = "github";
  const layout = new HookHarness();
  const githubSubtree = { editor: "same mounted draft owner" };
  layout.load(
    new URL(
      "./containers/useSystemSettingsLayoutContainer.ts",
      import.meta.url,
    ),
    "useSystemSettingsLayoutContainer",
    {
      "next/navigation": {
        useSearchParams: () => new URLSearchParams({ section }),
      },
      "@/shared/lib/admin-navigation": { settingsSectionFromValue },
    },
  );
  harness.render();
  harness.flushEffects();
  const initial = harness.render();
  invoke(initial.onClientIdChange, "draft-client-not-saved");
  for (const destination of ["github", "audit", "github"]) {
    section = destination;
    const renderedLayout = layout.render({
      sections: { github: githubSubtree },
    });
    assert.equal(renderedLayout.activeSection, destination);
    assert.equal(record(renderedLayout.sections).github, githubSubtree);
    const current = harness.render();
    assert.equal(
      record(current.draft).clientId,
      "draft-client-not-saved",
      section,
    );
    assert.equal(record(current.draft).clientSecret, "");
    assert.equal(record(current.draft).privateKey, "");
  }
});

void test("actual settings container projects the producer impact once for view and confirmation", () => {
  const wire = {
    affected_user_count: 2,
    affected_installation_count: 3,
    affected_toolkit_count: 4,
    affected_agent_count: 5,
    confirmation_actions: ["activate", null, "reconnect"],
    provider_extension: { opaque: true },
  };
  const { harness, detail, confirmations } = setup(wire);
  harness.render();
  harness.flushEffects();
  let output = harness.render();
  const impact = record(output.candidateImpact);
  assert.equal(impact.affected_user_count, 2);
  assert.equal(impact.affected_agent_count, 5);
  assert.deepEqual(output.confirmationActions, ["activate", "reconnect"]);
  assert.equal(output.confirmationAction, "activate");
  assert.equal(record(record(output.state).detail).candidate, detail.candidate);
  invoke(output.onConfirmCandidate);
  assert.deepEqual(confirmations, [
    {
      candidateId: "candidate-1",
      expectedVersion: 4,
      confirmationAction: "activate",
    },
  ]);
  detail.candidate = {
    id: "candidate-2",
    impact: null,
    validation_status: "valid",
  };
  harness.render();
  harness.flushEffects();
  output = harness.render();
  assert.deepEqual(output.confirmationActions, []);
  assert.equal(output.confirmationAction, null);
  assert.equal(record(output.candidateImpact).affected_user_count, null);
  invoke(output.onConfirmCandidate);
  assert.equal(confirmations.length, 1);
  assert.deepEqual(wire.provider_extension, { opaque: true });
});
