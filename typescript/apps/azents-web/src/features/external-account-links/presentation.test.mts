import assert from "node:assert/strict";
import test from "node:test";
import {
  elevationScreenState,
  normalizeProviderAvailability,
} from "./presentation.ts";

void test("elevation waits for the real methods response", () => {
  assert.equal(
    elevationScreenState({ hasResponse: false, isError: false }),
    "loading",
  );
  assert.equal(
    elevationScreenState({ hasResponse: false, isError: true }),
    "error",
  );
  assert.equal(
    elevationScreenState({ hasResponse: true, isError: false }),
    "ready",
  );
});

void test("provider availability keeps only actionable providers in order", () => {
  assert.deepEqual(
    normalizeProviderAvailability([
      {
        provider: "discord",
        status: "unavailable",
        available: false,
        callback_url: null,
      },
      {
        provider: "slack",
        status: "ready",
        available: true,
        callback_url: "https://azents.example/callback",
      },
    ]),
    [{ provider: "slack", status: "ready", available: true }],
  );
});

void test("all unavailable providers produce an empty actionable list", () => {
  assert.deepEqual(
    normalizeProviderAvailability([
      {
        provider: "slack",
        status: "incomplete",
        available: false,
        callback_url: null,
      },
      {
        provider: "discord",
        status: "unavailable",
        available: false,
        callback_url: null,
      },
    ]),
    [],
  );
});

void test("missing provider availability is rejected instead of creating a dead control", () => {
  assert.equal(
    normalizeProviderAvailability([
      {
        provider: "slack",
        status: "ready",
        available: true,
        callback_url: "https://azents.example/callback",
      },
    ]),
    null,
  );
});
