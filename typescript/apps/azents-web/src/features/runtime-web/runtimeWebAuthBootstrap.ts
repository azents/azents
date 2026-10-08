export type RuntimeWebAuthResult =
  { type: "NAVIGATING" } | { type: "ERROR"; message: string };

declare global {
  interface Window {
    __azentsRuntimeWebAuth?: {
      root: HTMLElement;
      serviceId: string | null;
      result: Promise<RuntimeWebAuthResult>;
    };
  }
}

/**
 * Start authentication without waiting for the application bundle.
 *
 * Keep this function closure-free: its compiled source also executes inline in
 * the initial HTML. Only browser globals and declarations inside it are available.
 * Share the operation with hydration without mutating React-owned presentation.
 */
export function startRuntimeWebAuth(): Promise<RuntimeWebAuthResult> {
  const root = document.getElementById("runtime-web-auth");
  if (root === null) {
    return Promise.resolve({
      type: "ERROR",
      message: "Authentication screen is unavailable.",
    });
  }
  const serviceId = root.dataset.serviceId ?? null;
  const mainWebOrigin = root.dataset.mainWebOrigin;
  if (mainWebOrigin && window.location.origin !== mainWebOrigin) {
    window.location.replace(
      `${mainWebOrigin}/runtime-web/auth?service_id=${encodeURIComponent(serviceId ?? "")}`,
    );
    return Promise.resolve({ type: "NAVIGATING" });
  }
  if (
    window.__azentsRuntimeWebAuth?.root === root &&
    window.__azentsRuntimeWebAuth.serviceId === serviceId
  ) {
    return window.__azentsRuntimeWebAuth.result;
  }
  const result = (async (): Promise<RuntimeWebAuthResult> => {
    try {
      const response = await fetch("/runtime-web/auth/start", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serviceId }),
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        const message =
          typeof body === "object" &&
          body !== null &&
          "error" in body &&
          typeof body.error === "string"
            ? body.error
            : `Runtime Web authentication failed (${response.status}).`;
        return { type: "ERROR", message };
      }
      if (typeof body === "object" && body !== null && "mode" in body) {
        if (
          body.mode === "shared_cookie" &&
          "destination" in body &&
          typeof body.destination === "string"
        ) {
          window.location.assign(body.destination);
          return { type: "NAVIGATING" };
        }
        if (
          body.mode === "separate_domain" &&
          "brokerDestination" in body &&
          typeof body.brokerDestination === "string" &&
          "initiationId" in body &&
          typeof body.initiationId === "string"
        ) {
          const form = document.createElement("form");
          form.method = "POST";
          form.action = body.brokerDestination;
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "initiation_id";
          input.value = body.initiationId;
          form.append(input);
          document.body.append(form);
          form.submit();
          return { type: "NAVIGATING" };
        }
      }
      return { type: "ERROR", message: root.dataset.invalidResponse ?? "" };
    } catch (error) {
      return {
        type: "ERROR",
        message:
          error instanceof Error
            ? error.message
            : (root.dataset.failedMessage ?? ""),
      };
    }
  })();
  window.__azentsRuntimeWebAuth = { root, serviceId, result };
  return result;
}

export function runtimeWebAuthBootstrapScript(): string {
  return `void (${startRuntimeWebAuth.toString()})()`;
}
