import assert from "node:assert/strict";
import test from "node:test";
import { hasExactRequestOrigin } from "./request-origin-policy.ts";

void test("accepts only the exact configured origin", () => {
  const request = new Request("https://app.example.com/api/trpc", {
    method: "POST",
    headers: { Origin: "https://app.example.com" },
  });
  assert.equal(hasExactRequestOrigin(request, "https://app.example.com"), true);
  assert.equal(
    hasExactRequestOrigin(request, "https://other.example.com"),
    false,
  );
});

void test("rejects missing, sibling, path-bearing, and port-mismatched origins", () => {
  const missing = new Request("https://app.example.com/api/trpc", {
    method: "POST",
  });
  assert.equal(
    hasExactRequestOrigin(missing, "https://app.example.com"),
    false,
  );

  for (const origin of [
    "https://evil.example.com",
    "https://app.example.com:444",
  ]) {
    const request = new Request("https://app.example.com/api/trpc", {
      method: "POST",
      headers: { Origin: origin },
    });
    assert.equal(
      hasExactRequestOrigin(request, "https://app.example.com"),
      false,
    );
  }

  const exact = new Request("https://app.example.com/api/trpc", {
    method: "POST",
    headers: { Origin: "https://app.example.com" },
  });
  assert.equal(
    hasExactRequestOrigin(exact, "https://app.example.com/control"),
    false,
  );
});
