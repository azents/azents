import "server-only";
import { getPublicConfig } from "@/config";
import { isExpectedOrigin } from "./auth-policy";

export function hasExpectedOrigin(request: Request): boolean {
  return isExpectedOrigin(
    request.headers.get("Origin"),
    getPublicConfig().publicBaseUrl,
  );
}
