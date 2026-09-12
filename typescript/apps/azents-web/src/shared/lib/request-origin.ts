import "server-only";
import { getServerConfig } from "@/config/server";
import { hasExactRequestOrigin } from "./request-origin-policy";

export { hasExactRequestOrigin } from "./request-origin-policy";

export function mainWebOrigin(request: Request): string {
  const config = getServerConfig();
  const configured = config.runtimeWebGatewayMainWebOrigin;
  if (configured !== null) {
    return configured;
  }
  if (config.runtimeWebGatewayEnabled) {
    throw new Error("Runtime Web Main Web origin is not configured.");
  }
  return new URL(request.url).origin;
}

export function rejectUntrustedMainWebOrigin(
  request: Request,
): Response | null {
  return hasExactRequestOrigin(request, mainWebOrigin(request))
    ? null
    : Response.json({ error: "Forbidden origin" }, { status: 403 });
}
