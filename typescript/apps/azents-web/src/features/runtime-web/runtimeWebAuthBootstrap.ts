export type RuntimeWebAuthResult =
  { type: "NAVIGATING" } | { type: "ERROR"; message: string };

declare global {
  interface Window {
    __azentsRuntimeWebAuth?: {
      root: HTMLElement;
      serviceId: string | null;
      returnTarget: string;
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
  const suppliedTarget = root.dataset.returnTarget;
  if (typeof suppliedTarget !== "string") {
    return Promise.resolve({
      type: "ERROR",
      message: root.dataset.invalidResponse ?? "",
    });
  }
  let returnTarget = suppliedTarget;
  if (!returnTarget.includes("#")) {
    returnTarget += window.location.hash;
  }
  const mainWebOrigin = root.dataset.mainWebOrigin;
  if (mainWebOrigin && window.location.origin !== mainWebOrigin) {
    const currentTarget =
      window.location.pathname + window.location.search + window.location.hash;
    window.location.replace(
      `${mainWebOrigin}/runtime-web/auth?service_id=${encodeURIComponent(serviceId ?? "")}&return_to=${encodeURIComponent(currentTarget)}`,
    );
    return Promise.resolve({ type: "NAVIGATING" });
  }
  if (
    window.__azentsRuntimeWebAuth?.root === root &&
    window.__azentsRuntimeWebAuth.serviceId === serviceId &&
    window.__azentsRuntimeWebAuth.returnTarget === returnTarget
  ) {
    return window.__azentsRuntimeWebAuth.result;
  }
  const result = (async (): Promise<RuntimeWebAuthResult> => {
    try {
      const response = await fetch("/runtime-web/auth/start", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serviceId, returnTarget }),
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
          const target = document.createElement("input");
          target.type = "hidden";
          target.name = "return_target";
          target.value = returnTarget;
          form.append(target);
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
  window.__azentsRuntimeWebAuth = { root, serviceId, returnTarget, result };
  return result;
}

export function runtimeWebAuthBootstrapScript(): string {
  return `void (${startRuntimeWebAuth.toString()})()`;
}
