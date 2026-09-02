import assert from "node:assert/strict";
import test from "node:test";
import { createAuthProvider } from "./auth-provider.ts";

await test("path-prefixed auth uses native navigation without router races", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = Reflect.get(globalThis, "window");
  const hadWindow = Reflect.has(globalThis, "window");
  let responseStatus = 200;
  let currentHref =
    "https://example.com/console/login?returnTo=%2Fconsole%2Fusers";
  const replacements: string[] = [];

  Reflect.set(globalThis, "fetch", () =>
    Promise.resolve(
      new Response(JSON.stringify({}), {
        status: responseStatus,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  Reflect.set(globalThis, "window", {
    location: {
      get href(): string {
        return currentHref;
      },
      replace(url: string): void {
        replacements.push(url);
        currentHref = url;
      },
    },
  });

  try {
    const provider = createAuthProvider("https://example.com/console");
    assert.deepEqual(
      await provider.login({
        email: "admin@example.com",
        password: "password",
      }),
      { success: true },
    );
    assert.deepEqual(replacements, ["https://example.com/console/users"]);

    replacements.length = 0;
    currentHref = "https://example.com/console/users?page=2";
    responseStatus = 401;
    assert.deepEqual(await provider.check(), {
      authenticated: false,
      logout: true,
    });
    assert.deepEqual(replacements, [
      "https://example.com/console/login?returnTo=%2Fconsole%2Fusers%3Fpage%3D2",
    ]);

    replacements.length = 0;
    currentHref =
      "https://example.com/console/login?returnTo=%2Fconsole%2Fusers%3Fpage%3D2";
    assert.deepEqual(await provider.check(), {
      authenticated: false,
      logout: true,
    });
    assert.deepEqual(replacements, []);

    responseStatus = 200;
    assert.deepEqual(await provider.logout({}), { success: true });
    assert.deepEqual(replacements, ["https://example.com/console/login"]);
  } finally {
    Reflect.set(globalThis, "fetch", originalFetch);
    if (hadWindow) {
      Reflect.set(globalThis, "window", originalWindow);
    } else {
      Reflect.deleteProperty(globalThis, "window");
    }
  }
});

await test("dedicated-host auth preserves Refine redirect contracts", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = Reflect.get(globalThis, "window");
  const hadWindow = Reflect.has(globalThis, "window");
  let responseStatus = 200;
  let currentHref = "https://admin.example.com/login?to=%2Fusers";
  const replacements: string[] = [];

  Reflect.set(globalThis, "fetch", () =>
    Promise.resolve(
      new Response(JSON.stringify({}), {
        status: responseStatus,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  Reflect.set(globalThis, "window", {
    location: {
      get href(): string {
        return currentHref;
      },
      replace(url: string): void {
        replacements.push(url);
      },
    },
  });

  try {
    const provider = createAuthProvider("https://admin.example.com");
    assert.deepEqual(
      await provider.login({
        email: "admin@example.com",
        password: "password",
      }),
      { success: true, redirectTo: "/workspaces" },
    );

    currentHref = "https://admin.example.com/users";
    responseStatus = 401;
    assert.deepEqual(await provider.check(), {
      authenticated: false,
      redirectTo: "/login",
      logout: true,
    });
    assert.deepEqual(replacements, []);

    currentHref = "https://admin.example.com/login?to=%2Fusers";
    assert.deepEqual(await provider.check(), {
      authenticated: false,
      logout: true,
    });
  } finally {
    Reflect.set(globalThis, "fetch", originalFetch);
    if (hadWindow) {
      Reflect.set(globalThis, "window", originalWindow);
    } else {
      Reflect.deleteProperty(globalThis, "window");
    }
  }
});
