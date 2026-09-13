import "server-only";
import { cookies } from "next/headers";
import { getServerConfig } from "@/config/server";

export {
  admittedBrowserProfile,
  decodeMainBinding,
  encodeMainBinding,
} from "./runtime-web-auth-policy";

export const RUNTIME_WEB_MAIN_BINDING_COOKIE =
  "__Host-Azents-Runtime-Web-Binding";
export const RUNTIME_WEB_ORDINARY_PROBE_COOKIE =
  "Azents-Runtime-Web-Cookie-Probe";
export const RUNTIME_WEB_HTTP_PROBE_COOKIE =
  "__Http-Azents-Runtime-Web-Cookie-Probe";

export function runtimeWebConfiguration():
  | {
      type: "DISABLED";
    }
  | {
      type: "READY";
      authMode: "shared_cookie" | "separate_domain";
      brokerOrigin: string;
      cookieDomain: string;
      identityCookieName: string;
    } {
  const config = getServerConfig();
  if (!config.runtimeWebGatewayEnabled) {
    return { type: "DISABLED" };
  }
  if (
    config.runtimeWebGatewayBrokerOrigin === null ||
    config.runtimeWebGatewayCookieDomain === null
  ) {
    throw new Error("Runtime Web Gateway authentication is not configured.");
  }
  return {
    type: "READY",
    authMode: config.runtimeWebGatewayAuthMode,
    brokerOrigin: config.runtimeWebGatewayBrokerOrigin,
    cookieDomain: config.runtimeWebGatewayCookieDomain,
    identityCookieName: config.runtimeWebGatewayIdentityCookieName,
  };
}

export async function getSharedRuntimeWebIdentity(): Promise<string | null> {
  const configuration = runtimeWebConfiguration();
  if (
    configuration.type === "DISABLED" ||
    configuration.authMode !== "shared_cookie"
  ) {
    return null;
  }
  const cookieStore = await cookies();
  return cookieStore.get(configuration.identityCookieName)?.value ?? null;
}

export function clearSharedRuntimeWebIdentity(headers: Headers): void {
  const configuration = runtimeWebConfiguration();
  if (
    configuration.type === "DISABLED" ||
    configuration.authMode !== "shared_cookie"
  ) {
    return;
  }
  headers.append(
    "Set-Cookie",
    [
      `${configuration.identityCookieName}=`,
      `Domain=${configuration.cookieDomain}`,
      "Path=/",
      "Max-Age=0",
      "HttpOnly",
      "Secure",
      "SameSite=Strict",
    ].join("; "),
  );
}
