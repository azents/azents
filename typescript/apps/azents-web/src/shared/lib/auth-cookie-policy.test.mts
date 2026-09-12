import assert from "node:assert/strict";
import test from "node:test";
import { authCookiePolicy } from "./auth-cookie-policy.ts";

void test("uses host-only production names without legacy fallback", () => {
  assert.deepEqual(authCookiePolicy("production"), {
    names: {
      ACCESS_TOKEN: "__Host-Azents-Access",
      REFRESH_TOKEN: "__Host-Azents-Refresh",
      EXPIRES_AT: "__Host-Azents-Access-Expires-At",
    },
    secure: true,
    sameSite: "none",
  });
});

void test("keeps explicit insecure local and test cookie names", () => {
  const expected = {
    names: {
      ACCESS_TOKEN: "az-token",
      REFRESH_TOKEN: "az-refresh",
      EXPIRES_AT: "az-token-expires-at",
    },
    secure: false,
    sameSite: "lax",
  };
  assert.deepEqual(authCookiePolicy("development"), expected);
  assert.deepEqual(authCookiePolicy("test"), expected);
});

void test("keeps secure legacy cookies for the explicit testenv profile", () => {
  assert.deepEqual(authCookiePolicy("production", "testenv_legacy"), {
    names: {
      ACCESS_TOKEN: "az-token",
      REFRESH_TOKEN: "az-refresh",
      EXPIRES_AT: "az-token-expires-at",
    },
    secure: true,
    sameSite: "lax",
  });
});
