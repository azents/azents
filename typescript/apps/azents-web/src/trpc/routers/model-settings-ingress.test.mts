import assert from "node:assert/strict";
import test from "node:test";
import {
  agentCreateInputSchema,
  agentUpdateInputSchema,
  workspaceModelSettingsUpdateInputSchema,
} from "../model-settings-input-schemas.ts";

void test("Agent tRPC mutations reject removed singular model fields", () => {
  assert.equal(
    agentCreateInputSchema.safeParse({
      handle: "workspace",
      name: "Agent",
      model_selection: {
        llm_provider_integration_id: "integration-1",
        model_identifier: "model-1",
      },
    }).success,
    false,
  );
  assert.equal(
    agentUpdateInputSchema.safeParse({
      handle: "workspace",
      agentId: "agent-1",
      lightweight_model_selection: {
        llm_provider_integration_id: "integration-1",
        model_identifier: "model-1",
      },
    }).success,
    false,
  );
});

void test("Workspace tRPC mutation rejects removed default model fields", () => {
  assert.equal(
    workspaceModelSettingsUpdateInputSchema.safeParse({
      handle: "workspace",
      default_model_selection: {
        llm_provider_integration_id: "integration-1",
        model_identifier: "model-1",
      },
    }).success,
    false,
  );
});

void test("tRPC candidate settings reject the removed subagent field placement", () => {
  const result = agentCreateInputSchema.safeParse({
    handle: "workspace",
    name: "Agent",
    selectable_model_options: [
      {
        label: "default",
        candidates: [
          {
            model_selection: {
              llm_provider_integration_id: "integration-1",
              model_identifier: "model-1",
            },
            settings: {
              subagent_enabled: false,
            },
          },
        ],
      },
    ],
  });

  assert.equal(result.success, false);
});
