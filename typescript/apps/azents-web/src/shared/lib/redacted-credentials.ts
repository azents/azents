/**
 * Remove redacted edit placeholders that do not contain a credential edit.
 *
 * Credential forms keep discriminators such as `type` visible while secret values
 * remain blank. Editable collections are submitted even when empty so removals
 * are preserved.
 */
export function normalizeCredentialEdits(
  credentials: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (credentials === null) {
    return null;
  }
  return hasCredentialEdit(credentials) ? credentials : null;
}

function hasCredentialEdit(value: unknown, key?: string): boolean {
  if (key === "type" || value === null || value === "") {
    return false;
  }
  if (Array.isArray(value)) {
    return true;
  }
  if (typeof value === "object") {
    return Object.entries(value).some(([nestedKey, nestedValue]) =>
      hasCredentialEdit(nestedValue, nestedKey),
    );
  }
  return true;
}
