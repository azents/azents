import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import { Script } from "node:vm";
import * as mantine from "@mantine/core";
import { MantineProvider } from "@mantine/core";
import { createElement, isValidElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import {
  adminNavigation,
  SETTINGS_SECTIONS,
  settingsSectionFromValue,
} from "../../shared/lib/admin-navigation.ts";
import { googleApplicationDraft } from "./google-application-state.ts";
import type { GoogleApplicationDetail } from "@azents/admin-client";
import type { ComponentProps, ReactElement } from "react";

const require = createRequire(import.meta.url);

function loadComponent(
  file: string,
  name: string,
  boundaries: Record<string, unknown> = {},
): (props: unknown) => ReactElement {
  const exports: Record<string, unknown> = {};
  const source = ts.transpileModule(
    readFileSync(new URL(file, import.meta.url), "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  new Script(source).runInNewContext({
    exports,
    require: (id: string): unknown =>
      id === "@mantine/core" ? mantine : (boundaries[id] ?? require(id)),
  });
  const component = exports[name];
  assert.ok(typeof component === "function");
  return (props): ReactElement => {
    const element: unknown = Reflect.apply(component, null, [props]);
    assert.ok(isValidElement(element));
    return element;
  };
}

function render(
  component: (props: unknown) => ReactElement,
  props: unknown,
): string {
  return renderToStaticMarkup(
    createElement(MantineProvider, {}, component(props)),
  );
}

const Guide = loadComponent(
  "./components/GoogleApplicationSetupGuide.tsx",
  "GoogleApplicationSetupGuide",
);
const Card = loadComponent(
  "./components/GoogleApplicationCard.tsx",
  "GoogleApplicationCard",
  {
    "./GoogleApplicationSetupGuide": { GoogleApplicationSetupGuide: Guide },
  },
);
const Layout = loadComponent(
  "./components/SystemSettingsLayout.tsx",
  "SystemSettingsLayout",
  {
    "@/shared/lib/admin-navigation": { SETTINGS_SECTIONS },
  },
);

void test("the shared Admin shell renders all destinations and settings in a single navigation", () => {
  const Shell = loadComponent(
    "../../shared/components/AdminShell.tsx",
    "AdminShell",
    {
      "next/link": (props: ComponentProps<"a">): ReactElement =>
        createElement("a", {
          ...props,
          className: `${props.className ?? ""} test-next-link`,
        }),
    },
  );
  const navigation = adminNavigation(
    "https://example.invalid/admin",
    "/admin/system-settings",
    "google",
  );
  const html = render(Shell, {
    ...navigation,
    children: Layout({
      sections: { google: Card(cardProps()) },
      activeSection: "google",
    }),
    homeHref: "/admin/",
    opened: false,
    onToggleNavigation: (): void => {},
    onCloseNavigation: (): void => {},
    user: null,
    preference: "light",
    mode: "light",
    onPreferenceChange: (): void => {},
    onLogout: (): void => {},
  });
  assert.equal((html.match(/aria-label="Admin navigation"/g) ?? []).length, 1);
  assert.equal((html.match(/aria-current="page"/g) ?? []).length, 1);
  for (const item of navigation.groups.flatMap((group) => group.items)) {
    const anchor = [...html.matchAll(/<a\b[^>]*>/g)]
      .map((match) => match[0])
      .find((tag) => tag.includes(`href="${item.href}"`));
    assert.ok(anchor);
    assert.equal(anchor.includes("test-next-link"), true);
  }
  assert.match(html, /aria-label="Color scheme"/);
  assert.match(html, /Save application settings/);
});

const detail: GoogleApplicationDetail = {
  status: "not_configured",
  client_id: null,
  callback_url: "https://azents.example.invalid/oauth/google/callback",
  picker_status: "not_configured",
  picker_api_key: null,
  picker_app_id: null,
  picker_api_key_source: "unset",
  picker_app_id_source: "unset",
  service_access_verified: false,
  section: "google_oauth",
  schema_version: 1,
  admin_version: 1,
  client_id_source: "unset",
  client_secret_source: "unset",
  client_secret_configured: false,
};
function cardProps(overrides: Partial<GoogleApplicationDetail> = {}): unknown {
  const current = { ...detail, ...overrides };
  return {
    state: {
      type: "LOADED",
      detail: current,
      draft: googleApplicationDraft(current),
      dirty: false,
      saving: false,
      reloadRequired: false,
      error: null,
      onDraftChange: (): void => {},
      onSave: (): void => {},
      onReload: (): void => {},
    },
  };
}

void test("Google guide renders the complete operator setup flow with official links", () => {
  const html = render(Guide, {});
  for (const step of [
    "Choose a Cloud project and enable the APIs",
    "Configure the OAuth consent screen",
    "Create a Web application client",
    "Optionally prepare Google Picker",
    "Save credentials, then connect a Toolkit",
  ]) {
    assert.ok(html.includes(step), step);
  }
  for (const path of [
    "guides/configure-oauth-consent",
    "drive/picker/guides/web-picker",
  ]) {
    assert.ok(
      html.includes(`href="https://developers.google.com/workspace/${path}"`),
    );
  }
  assert.match(html, /Authorized redirect URIs/);
  assert.match(html, /Test users/);
  for (const scope of [
    "calendar.calendarlist.readonly",
    "calendar.events.readonly",
    "calendar.events.freebusy",
    "calendar.events",
    "drive.readonly",
    "drive.file",
    "gmail.readonly",
    "gmail.compose",
    "gmail.modify",
    "drive",
    "gmail.send",
    "gmail.settings.basic",
  ]) {
    assert.ok(html.includes(`https://www.googleapis.com/auth/${scope}`));
  }
  assert.match(html, /AZ_GOOGLE_OAUTH_CLIENT_SECRET/);
  assert.match(
    html,
    /does not test live service access or Google verification/,
  );
  assert.match(html, /Compose and modify grants include supported sending/);
  assert.match(html, /whole reads but only app-file writes/);
  assert.match(html, /AZ_GOOGLE_PICKER_API_KEY/);
  assert.match(html, /numeric Cloud project number/);
});

void test("Google card opens help for setup and preserves the server callback and write-only secret", () => {
  const html = render(Card, cardProps());
  assert.match(html, /aria-expanded="true"/);
  assert.ok(html.includes(detail.callback_url ?? "missing callback"));
  assert.match(html, /Save application settings/);
  const configured = render(
    Card,
    cardProps({
      status: "configured_unverified",
      client_id_source: "environment",
      client_secret_source: "environment",
      client_secret_configured: true,
    }),
  );
  assert.match(configured, /aria-expanded="false"/);
  assert.match(configured, /read-only here/);
  assert.match(
    configured,
    /Existing secret plaintext is never returned|Owned by process environment/,
  );
  assert.match(
    render(Card, cardProps({ callback_url: null })),
    /Unavailable until the public Web URL is configured/,
  );
  assert.match(
    render(Card, { state: { type: "ERROR", onReload: (): void => {} } }),
    /Unable to load Google application settings/,
  );
});

void test("settings navigation accepts known query values and safely defaults unknown ones", () => {
  for (const section of SETTINGS_SECTIONS) {
    assert.equal(settingsSectionFromValue(section.value), section.value);
  }
  assert.equal(settingsSectionFromValue(null), "google");
  assert.equal(settingsSectionFromValue("unknown"), "google");
});

void test("settings layout exposes one section while retaining every draft subtree", () => {
  const sections = Object.fromEntries(
    SETTINGS_SECTIONS.map(({ value }) => [
      value,
      createElement("input", {
        name: `${value}-draft`,
        defaultValue: `draft-${value}`,
      }),
    ]),
  );
  for (const section of SETTINGS_SECTIONS) {
    const html = render(Layout, {
      sections,
      activeSection: section.value,
    });
    const hidden = html.match(/<section[^>]*style="display:none"/g) ?? [];
    assert.equal(hidden.length, SETTINGS_SECTIONS.length - 1);
    for (const { value } of SETTINGS_SECTIONS) {
      assert.ok(html.includes(`value="draft-${value}"`));
    }
  }
});

void test("GitHub failure stays within its section and does not replace the settings workspace", () => {
  const Page = loadComponent(
    "./components/SystemSettingsPageContent.tsx",
    "SystemSettingsPageContent",
    {
      "../GoogleApplicationCardContainer": {
        GoogleApplicationCardContainer: (): ReactElement =>
          createElement("p", {}, "Google settings available"),
      },
      "../SystemSettingsLayoutContainer": {
        SystemSettingsLayoutContainer: (props: {
          sections: unknown;
        }): ReactElement =>
          Layout({
            ...props,
            activeSection: "google",
          }),
      },
      "./ExternalAccountOAuthCards": {
        ExternalAccountOAuthCards: (): ReactElement =>
          createElement("p", {}, "Account linking available"),
      },
      "./HistoricalMemoryExecutionCard": {
        HistoricalMemoryExecutionCard: (): ReactElement =>
          createElement("p", {}, "Memory settings available"),
      },
    },
  );
  const html = render(Page, {
    state: { type: "ERROR", message: "GitHub unavailable" },
    auditState: { type: "LOADED", events: [], total: 0 },
    externalFilesState: { type: "LOADING" },
    externalFilesDraft: { outboundMaxFileMiB: "", outboundMaxActionMiB: "" },
  });
  assert.match(html, /Google settings available/);
  assert.match(html, /Account linking available/);
  assert.match(html, /Memory settings available/);
  assert.match(html, /Unable to load GitHub settings/);
  assert.match(html, /No System Settings audit events yet/);
});
