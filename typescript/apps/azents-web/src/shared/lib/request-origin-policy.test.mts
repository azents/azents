import assert from "node:assert/strict";
import test from "node:test";
import {
  externalRequestOrigin,
  hasExactRequestOrigin,
} from "./request-origin-policy.ts";

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

void test("resolves the externally visible origin behind a reverse proxy", () => {
  const request = new Request("http://azents-web:3000/api/trpc", {
    method: "POST",
    headers: {
      Host: "azents-web:3000",
      "X-Forwarded-Host": "app.example.com:8443",
      "X-Forwarded-Proto": "https",
    },
  });

  assert.equal(externalRequestOrigin(request), "https://app.example.com:8443");
});

void test("falls back to the request URL for ambiguous forwarded origins", () => {
  const request = new Request("http://azents-web:3000/api/trpc", {
    method: "POST",
    headers: {
      "X-Forwarded-Host": "app.example.com, proxy.internal",
      "X-Forwarded-Proto": "https",
    },
  });

  assert.equal(externalRequestOrigin(request), "http://azents-web:3000");
});
