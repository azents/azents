import assert from "node:assert/strict";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { runtimeWebAuthBootstrapScript } from "./runtimeWebAuthBootstrap.ts";

class Element {
  dataset: Record<string, string> = {};
  method = "";
  action = "";
  type = "";
  name = "";
  value = "";
  submitted = false;
  children: Element[] = [];

  append(child: Element): void {
    this.children.push(child);
  }

  submit(): void {
    this.submitted = true;
  }
}

class Browser {
  root = new Element();
  body = new Element();
  calls: Array<{ url: string; options: RequestInit }> = [];
  destination: string | null = null;
  response: Promise<Response>;
  window = {
    location: {
      origin: "https://main.test",
      pathname: "/",
      search: "",
      hash: "",
      replace: (destination: string): void => {
        this.destination = destination;
      },
      assign: (destination: string): void => {
        this.destination = destination;
      },
    },
  };

  constructor(response: Promise<Response>) {
    this.response = response;
    this.root.dataset = {
      serviceId: "s".repeat(32),
      returnTarget: "/",
      invalidResponse: "Invalid authentication response.",
      failedMessage: "Authentication failed.",
    };
  }
}

async function executeAndSettle(browser: Browser): Promise<unknown> {
  const script = runtimeWebAuthBootstrapScript().replace(/^void /, "");
  const execution: unknown = runInNewContext(script, {
    document: {
      getElementById: () => browser.root,
      createElement: () => new Element(),
      body: browser.body,
    },
    window: browser.window,
    fetch: async (url: string, options: RequestInit): Promise<Response> => {
      browser.calls.push({ url, options });
      return await browser.response;
    },
    Error,
  });
  return await execution;
}

void test("serialized bootstrap authenticates without any application imports", async () => {
  const browser = new Browser(
    Promise.resolve(
      Response.json({
        mode: "shared_cookie",
        destination: "https://service.test/",
      }),
    ),
  );
  await executeAndSettle(browser);
  assert.equal(browser.destination, "https://service.test/");
  assert.equal(
    JSON.stringify(browser.calls),
    JSON.stringify([
      {
        url: "/runtime-web/auth/start",
        options: {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            serviceId: "s".repeat(32),
            returnTarget: "/",
          }),
        },
      },
    ]),
  );
});

void test("separate-domain authentication retains the native broker POST", async () => {
  const browser = new Browser(
    Promise.resolve(
      Response.json({
        mode: "separate_domain",
        brokerDestination: "https://broker.test/bind",
        initiationId: "initiation-id",
      }),
    ),
  );
  await executeAndSettle(browser);
  const [form] = browser.body.children;
  assert.ok(form);
  assert.equal(form.method, "POST");
  assert.equal(form.action, "https://broker.test/bind");
  assert.equal(form.submitted, true);
  const [input] = form.children;
  assert.ok(input);
  assert.equal(input.type, "hidden");
  assert.equal(input.name, "initiation_id");
  assert.equal(input.value, "initiation-id");
  const target = form.children[1];
  assert.ok(target);
  assert.equal(target.name, "return_target");
  assert.equal(target.value, "/");
  assert.equal(browser.destination, null);
});

void test("inline execution and later hydration share one pending operation", async () => {
  const { promise, resolve } = Promise.withResolvers<Response>();
  const browser = new Browser(promise);
  const first = executeAndSettle(browser);
  const second = executeAndSettle(browser);
  assert.equal(browser.calls.length, 1);
  resolve(
    Response.json({
      mode: "shared_cookie",
      destination: "https://service.test/",
    }),
  );
  await Promise.all([first, second]);
  assert.equal(browser.destination, "https://service.test/");
});

for (const result of [
  {
    body: { error: "Authentication required" },
    status: 401,
    message: "Authentication required",
  },
  {
    body: { mode: "unknown" },
    status: 200,
    message: "Invalid authentication response.",
  },
]) {
  void test(`hydration receives the existing error result for ${result.message}`, async () => {
    const browser = new Browser(
      Promise.resolve(Response.json(result.body, { status: result.status })),
    );
    const first = await executeAndSettle(browser);
    const hydrated = await executeAndSettle(browser);
    assert.equal(
      JSON.stringify(first),
      JSON.stringify({ type: "ERROR", message: result.message }),
    );
    assert.equal(first, hydrated);
    assert.equal(browser.calls.length, 1);
    assert.equal(browser.body.children.length, 0);
    assert.deepEqual(browser.root.dataset, {
      serviceId: "s".repeat(32),
      returnTarget: "/",
      invalidResponse: "Invalid authentication response.",
      failedMessage: "Authentication failed.",
    });
  });
}

void test("a new authentication screen starts its own operation", async () => {
  const browser = new Browser(
    Promise.resolve(Response.json({ mode: "unknown" })),
  );
  await executeAndSettle(browser);
  browser.root = new Element();
  browser.root.dataset.serviceId = "t".repeat(32);
  browser.root.dataset.returnTarget = "/";
  await executeAndSettle(browser);
  assert.equal(browser.calls.length, 2);
});

void test("an authentication document restored at the service origin navigates to Main Web first", async () => {
  const browser = new Browser(
    Promise.resolve(Response.json({ mode: "unknown" })),
  );
  browser.root.dataset.mainWebOrigin = "https://main.test";
  browser.window.location.origin = "https://service.test";
  browser.window.location.pathname = "/catalog/item";
  browser.window.location.search = "?tag=one&tag=two";
  browser.window.location.hash = "#details";
  await executeAndSettle(browser);
  assert.equal(
    browser.destination,
    `https://main.test/runtime-web/auth?service_id=${"s".repeat(32)}&return_to=${encodeURIComponent("/catalog/item?tag=one&tag=two#details")}`,
  );
  assert.equal(browser.calls.length, 0);
});

void test("bootstrap carries the original query and inherited fragment into authentication", async () => {
  const browser = new Browser(
    Promise.resolve(Response.json({ mode: "unknown" })),
  );
  browser.root.dataset.returnTarget =
    "/catalog/item?tag=one&tag=two&next=%2Fbasket";
  browser.window.location.hash = "#details";
  await executeAndSettle(browser);
  assert.equal(
    browser.calls[0]?.options.body,
    JSON.stringify({
      serviceId: "s".repeat(32),
      returnTarget: "/catalog/item?tag=one&tag=two&next=%2Fbasket#details",
    }),
  );
});

void test("a fragment already carried through login is not appended twice", async () => {
  const browser = new Browser(
    Promise.resolve(
      Response.json({
        mode: "separate_domain",
        brokerDestination: "https://broker.test/bind",
        initiationId: "initiation-id",
      }),
    ),
  );
  browser.root.dataset.returnTarget = "/catalog/item?view=grid#details";
  browser.window.location.hash = "#details";
  await executeAndSettle(browser);
  assert.equal(
    browser.body.children[0]?.children[1]?.value,
    "/catalog/item?view=grid#details",
  );
});
