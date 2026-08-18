export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function getString(value: unknown, fallback = ""): string {
  return isString(value) ? value : fallback;
}

export function getOptionalString(value: unknown): string | null {
  return isString(value) ? value : null;
}

export function getStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(isString) : [];
}

export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

export function getArray<T>(
  value: unknown,
  predicate: (item: unknown) => item is T,
): T[] {
  return Array.isArray(value) ? value.filter(predicate) : [];
}

export function isOneOf<T extends string>(
  value: unknown,
  candidates: readonly T[],
): value is T {
  return (
    typeof value === "string" &&
    candidates.some((candidate) => candidate === value)
  );
}

export function parseJsonRecord(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}
