import assert from "node:assert/strict";
import test from "node:test";
import { browserDownloadRedirect } from "./browserDownloadRedirect.ts";

void test("forwards only a capability and refreshed cookies without consuming bytes", (): void => {
  const backend = new Response("must not read this body", {
    status: 302,
    headers: { Location: "https://objects.test/file?signature=redacted" },
  });
  const headers = new Headers({ "Set-Cookie": "refreshed=token; HttpOnly" });

  const response = browserDownloadRedirect(backend, headers);

  assert.equal(response.status, 302);
  assert.equal(response.body, null);
  assert.equal(backend.bodyUsed, false);
  assert.equal(
    response.headers.get("location"),
    "https://objects.test/file?signature=redacted",
  );
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(response.headers.get("set-cookie"), "refreshed=token; HttpOnly");
});

void test("denials never return a redirect or inspect the backend body", (): void => {
  for (const status of [401, 403, 404, 410, 413]) {
    const backend = new Response("internal backend failure", { status });
    const response = browserDownloadRedirect(backend, new Headers());
    assert.equal(response.status, status);
    assert.equal(response.headers.get("location"), null);
    assert.equal(backend.bodyUsed, false);
  }
});

void test("an old body relay is rejected instead of becoming a compatibility fallback", (): void => {
  const backend = new Response("old file bytes", { status: 200 });
  assert.throws(
    () => browserDownloadRedirect(backend, new Headers()),
    /authorized redirect/,
  );
  assert.equal(backend.bodyUsed, false);
});

void test("malformed capabilities fail without exposing the supplied location", (): void => {
  for (const location of [
    null,
    "not a URL?signature=private",
    "ftp://objects.test/file",
    "https://secret:credential@objects.test/file",
  ]) {
    const headers = new Headers();
    if (location !== null) {
      headers.set("Location", location);
    }
    const backend = new Response(null, { status: 302, headers });
    assert.throws(
      () => browserDownloadRedirect(backend, new Headers()),
      (error: unknown): boolean =>
        error instanceof Error &&
        /File download redirect/.test(error.message) &&
        !error.message.includes("private") &&
        !error.message.includes("credential"),
    );
  }
});
