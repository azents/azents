import type { GooglePickerTokenOutput } from "@azents/public-client";

interface Picker {
  setVisible: (visible: boolean) => void;
  dispose: () => void;
}
interface PickerBuilder {
  setOAuthToken: (token: string) => PickerBuilder;
  setDeveloperKey: (key: string) => PickerBuilder;
  setAppId: (id: string) => PickerBuilder;
  setOrigin: (origin: string) => PickerBuilder;
  addView: (view: string) => PickerBuilder;
  setCallback: (callback: (response: unknown) => void) => PickerBuilder;
  build: () => Picker;
}
export interface GooglePickerApi {
  PickerBuilder: new () => PickerBuilder;
  ViewId: { DOCS: string };
}
interface GapiLoader {
  load: (
    name: string,
    options: {
      callback: () => void;
      onerror: () => void;
      timeout: number;
      ontimeout: () => void;
    },
  ) => void;
}
declare global {
  interface Window {
    gapi?: GapiLoader;
    google?: { picker?: GooglePickerApi };
  }
}
let sdk: Promise<GooglePickerApi> | null = null;
/** Only the official browser SDK is loaded; no credentials enter this cache. */
export function loadGooglePicker(): Promise<GooglePickerApi> {
  if (sdk != null) {
    return sdk;
  }
  const pending = new Promise<GooglePickerApi>((resolve, reject) => {
    let settled = false;
    let script: HTMLScriptElement | null = null;
    const fail = (): void => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      script?.remove();
      reject(new Error("Google Picker is unavailable."));
    };
    const timer = setTimeout(fail, 15000);
    const load = (): void => {
      if (settled) {
        return;
      }
      const gapi = window.gapi;
      if (gapi == null) {
        fail();
        return;
      }
      try {
        gapi.load("picker", {
          callback: () => {
            if (settled) {
              return;
            }
            const api = window.google?.picker;
            if (api == null) {
              fail();
            } else {
              settled = true;
              clearTimeout(timer);
              resolve(api);
            }
          },
          onerror: fail,
          timeout: 15000,
          ontimeout: fail,
        });
      } catch {
        fail();
      }
    };
    if (window.gapi != null) {
      load();
      return;
    }
    script = document.createElement("script");
    script.src = "https://apis.google.com/js/api.js";
    script.async = true;
    script.onload = load;
    script.onerror = fail;
    document.head.append(script);
  });
  sdk = pending;
  void pending.catch(() => {
    if (sdk === pending) {
      sdk = null;
    }
  });
  return pending;
}
export type GooglePickerResult =
  | { type: "SELECTED"; count: number }
  | { type: "CANCELLED" }
  | { type: "EXPIRED" };
export interface GooglePickerHandle {
  close: () => void;
}
/** The token lives only in this SDK instance and is discarded with its iframe. */
export function openGooglePicker(
  api: GooglePickerApi,
  receipt: GooglePickerTokenOutput,
  onResult: (result: GooglePickerResult) => void,
): GooglePickerHandle {
  const remaining = Date.parse(receipt.expires_at) - Date.now();
  if (!Number.isFinite(remaining) || remaining <= 0) {
    throw new Error("Google Picker credential expired.");
  }
  let picker: Picker | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  const dispose = (): void => {
    if (closed) {
      return;
    }
    closed = true;
    if (timer != null) {
      clearTimeout(timer);
    }
    timer = null;
    picker?.setVisible(false);
    picker?.dispose();
    picker = null;
  };
  const finish = (result: GooglePickerResult): void => {
    dispose();
    onResult(result);
  };
  picker = new api.PickerBuilder()
    .setOAuthToken(receipt.access_token)
    .setDeveloperKey(receipt.api_key)
    .setAppId(receipt.app_id)
    .setOrigin(window.location.origin)
    .addView(api.ViewId.DOCS)
    .setCallback((response) => {
      if (
        closed ||
        response == null ||
        typeof response !== "object" ||
        !("action" in response)
      ) {
        return;
      }
      if (response.action === "cancel") {
        finish({ type: "CANCELLED" });
      }
      if (response.action === "picked") {
        // IDs and URLs are untrusted interaction data, not persisted access rules.
        const docs =
          "docs" in response && Array.isArray(response.docs)
            ? response.docs
            : [];
        finish({ type: "SELECTED", count: docs.length });
      }
    })
    .build();
  timer = setTimeout(() => finish({ type: "EXPIRED" }), remaining);
  try {
    picker.setVisible(true);
  } catch {
    dispose();
    throw new Error("Google Picker could not open.");
  }
  return { close: dispose };
}
