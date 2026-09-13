/**
 * Remove redacted edit placeholders that do not contain a credential value.
 *
 * Credential forms keep discriminators such as `type` visible while secret values
 * remain blank. Nested objects need the same treatment as flat credential forms.
 */
export function normalizeCredentialEdits(
  credentials: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (credentials === null) {
    return null;
  }
  return hasCredentialValue(credentials) ? credentials : null;
}

function hasCredentialValue(value: unknown, key?: string): boolean {
  if (key === "type" || value === null || value === "") {
    return false;
  }
  if (Array.isArray(value)) {
    return value.some((item) => hasCredentialValue(item));
  }
  if (typeof value === "object") {
    return Object.entries(value).some(([nestedKey, nestedValue]) =>
      hasCredentialValue(nestedValue, nestedKey),
    );
  }
  return true;
}
