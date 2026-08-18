import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_LOGIN_REDIRECT,
  getPostLoginRedirect,
  getSafeLoginNext,
} from "./login-redirect.ts";

void test("preserves valid same-origin path references for login-step propagation", () => {
  assert.equal(getSafeLoginNext("/w/example"), "/w/example");
  assert.equal(
    getSafeLoginNext("/w/example?tab=agents#active"),
    "/w/example?tab=agents#active",
  );
});

void test("rejects invalid targets during login-step propagation", () => {
  assert.equal(getSafeLoginNext(null), null);
  assert.equal(getSafeLoginNext(), null);
  assert.equal(getSafeLoginNext("https://example.test/phishing"), null);
  assert.equal(getSafeLoginNext("//example.test/phishing"), null);
});

void test("password success preserves a relative target and rejects an absolute target", () => {
  assert.equal(getPostLoginRedirect("/settings"), "/settings");
  assert.equal(
    getPostLoginRedirect("https://example.test/phishing"),
    DEFAULT_LOGIN_REDIRECT,
  );
});

void test("email OTP success falls back for absent and scheme-relative targets", () => {
  assert.equal(getPostLoginRedirect(null), DEFAULT_LOGIN_REDIRECT);
  assert.equal(
    getPostLoginRedirect("//example.test/phishing"),
    DEFAULT_LOGIN_REDIRECT,
  );
});

void test("rejects path text that resolves to another origin", () => {
  assert.equal(getSafeLoginNext("/\\example.test/phishing"), null);
  assert.equal(
    getPostLoginRedirect("/\\example.test/phishing"),
    DEFAULT_LOGIN_REDIRECT,
  );
});
