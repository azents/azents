import { normalizeCredentialEdits } from "../lib/redacted-credentials.ts";

/** Blank write-only inputs mean omitted; explicit null remains an explicit edit. */
export function normalizeGitHubUserCredentialEdits(
  credentials: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (credentials?.type === "github_app_platform_user") {
    return { type: "github_app_platform_user" };
  }
  if (credentials?.type !== "github_app_user") {
    return normalizeCredentialEdits(credentials);
  }
  const fields: Record<string, unknown> = { type: "github_app_user" };
  for (const key of ["app_id", "client_id", "private_key", "client_secret"]) {
    const value = credentials[key];
    if (value !== void 0 && value !== "") {
      fields[key] = value;
    }
  }
  return Object.keys(fields).length === 1 ? null : fields;
}

export function missingNewGitHubUserRegistration(
  credentials: Record<string, unknown> | null,
): string[] {
  return ["app_id", "client_id", "private_key", "client_secret"].filter(
    (key) =>
      typeof credentials?.[key] !== "string" || credentials[key].trim() === "",
  );
}

/** A saved source discriminator is not a registration change. */
export function gitHubUserRegistrationDirty(
  savedMode: unknown,
  currentMode: unknown,
  credentials: Record<string, unknown> | null,
): boolean {
  if (savedMode !== currentMode) {
    return true;
  }
  if (currentMode === "github_app_platform_user") {
    return false;
  }
  return normalizeGitHubUserCredentialEdits(credentials) != null;
}
