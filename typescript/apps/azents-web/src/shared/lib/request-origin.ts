import "server-only";
import { getServerConfig } from "@/config/server";
import {
  externalRequestOrigin,
  hasExactRequestOrigin,
} from "./request-origin-policy";

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
  return externalRequestOrigin(request);
}

export function rejectUntrustedMainWebOrigin(
  request: Request,
): Response | null {
  return hasExactRequestOrigin(request, mainWebOrigin(request))
    ? null
    : Response.json({ error: "Forbidden origin" }, { status: 403 });
}
