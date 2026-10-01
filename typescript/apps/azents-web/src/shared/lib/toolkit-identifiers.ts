export const TOOLKIT_SLUG_REGEX = /^[a-z0-9_]+$/;

const TOOLKIT_SLUG_MAX_LENGTH = 100;
const TOOLKIT_TRIM_PATTERN =
  /^[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g;
const TOOLKIT_SEPARATOR_PATTERN =
  /[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000-]+/g;

export type ToolkitIdentifierField = "name" | "slug";

export interface ToolkitIdentifierValidationError {
  field: ToolkitIdentifierField;
  detail: string;
}

export function trimToolkitWhitespace(value: string): string {
  return value.replace(TOOLKIT_TRIM_PATTERN, "");
}

export function resolveToolkitName(
  toolkitType: string,
  canonicalName: string,
  submittedName: string | null,
): string | ToolkitIdentifierValidationError {
  const normalized =
    submittedName == null ? "" : trimToolkitWhitespace(submittedName);
  if (normalized) {
    return normalized;
  }
  if (toolkitType === "mcp") {
    return {
      field: "name",
      detail: "Name is required for generic MCP Toolkits.",
    };
  }
  return canonicalName;
}

export function slugifyToolkitName(value: string): string {
  const asciiValue = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\x00-\x7f]/g, "");
  return asciiValue
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, TOOLKIT_SLUG_MAX_LENGTH)
    .replace(/_+$/g, "");
}

export function resolveDefaultToolkitSlug(
  effectiveName: string,
  canonicalName: string,
): string {
  const slug = slugifyToolkitName(effectiveName);
  if (slug) {
    return slug;
  }
  const fallback = slugifyToolkitName(canonicalName);
  if (!fallback) {
    throw new Error("Toolkit Provider canonical Name cannot produce a Slug.");
  }
  return fallback;
}

export function normalizeExplicitToolkitSlug(
  submittedSlug: string,
): string | null | ToolkitIdentifierValidationError {
  const trimmed = trimToolkitWhitespace(submittedSlug);
  if (!trimmed) {
    return null;
  }
  const normalized = trimmed
    .replace(/[A-Z]/g, (character) => character.toLowerCase())
    .replace(TOOLKIT_SEPARATOR_PATTERN, "_")
    .replace(/_+/g, "_");
  if (
    normalized.length > TOOLKIT_SLUG_MAX_LENGTH ||
    !TOOLKIT_SLUG_REGEX.test(normalized)
  ) {
    return {
      field: "slug",
      detail:
        "Slug must contain at most 100 lowercase ASCII letters, numbers, or underscores.",
    };
  }
  return normalized;
}
