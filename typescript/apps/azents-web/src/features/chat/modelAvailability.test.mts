import assert from "node:assert/strict";
import test from "node:test";

import {
  modelAvailabilityBadge,
  modelAvailabilityRemainingMinutes,
  type ModelAvailabilityViewState,
} from "./modelAvailability.ts";

const cooldown: ModelAvailabilityViewState = {
  type: "LOADED",
  data: {
    semantic_label: "Default",
    primary: {
      llm_provider_integration_id: "integration-primary",
      model_identifier: "gpt-primary",
    },
    primary_display_name: "GPT Primary",
    state: "cooldown",
    deadline: "2026-09-13T04:05:00Z",
    server_time: "2026-09-13T04:00:00Z",
    first_usable_fallback_display_name: "GPT Fallback",
    reservation: null,
  },
};

void test("availability badges require the active semantic label", () => {
  assert.equal(modelAvailabilityBadge(cooldown, "Default"), "fallback");
  assert.equal(modelAvailabilityBadge(cooldown, "Other"), null);
  assert.equal(
    modelAvailabilityBadge(
      {
        type: "LOADED",
        data: { ...cooldown.data, state: "primary_next" },
      },
      "Default",
    ),
    "primary_next",
  );
});

void test("availability deadlines use server-relative whole minutes", () => {
  const observedAtMs = Date.parse("2026-09-13T04:00:10Z");
  assert.equal(
    modelAvailabilityRemainingMinutes(
      cooldown.data,
      observedAtMs,
      observedAtMs,
    ),
    5,
  );
  assert.equal(
    modelAvailabilityRemainingMinutes(
      cooldown.data,
      observedAtMs,
      observedAtMs + 61_000,
    ),
    4,
  );
  assert.equal(
    modelAvailabilityRemainingMinutes(
      cooldown.data,
      observedAtMs,
      observedAtMs + 300_000,
    ),
    null,
  );
  assert.equal(
    modelAvailabilityRemainingMinutes(
      { ...cooldown.data, deadline: null },
      observedAtMs,
      observedAtMs,
    ),
    null,
  );
});
