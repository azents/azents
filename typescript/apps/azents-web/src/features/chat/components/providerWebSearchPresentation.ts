import type { ProviderToolCall } from "../types";

export interface ProviderWebSearchResult {
  excerpt: string | null;
  title: string;
  uri: string;
}

export interface ProviderWebSearchPresentation {
  query: string | null;
  results: ProviderWebSearchResult[];
  summary: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function searchQuery(argumentsText: string): string | null {
  try {
    const value: unknown = JSON.parse(argumentsText);
    if (!isRecord(value) || typeof value.query !== "string") {
      return null;
    }
    const query = value.query.trim();
    return query.length > 0 ? query : null;
  } catch {
    return null;
  }
}

function httpUri(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  try {
    const uri = new URL(value);
    return uri.protocol === "https:" || uri.protocol === "http:"
      ? uri.toString()
      : null;
  } catch {
    return null;
  }
}

/** Project verified provider web-search semantics without provider-specific labels. */
export function providerWebSearchPresentation(
  toolCall: ProviderToolCall,
): ProviderWebSearchPresentation | null {
  if (toolCall.name !== "web_search") {
    return null;
  }
  const results = (toolCall.references ?? []).flatMap((reference) => {
    if (reference.kind !== "url") {
      return [];
    }
    const uri = httpUri(reference.uri);
    if (uri === null) {
      return [];
    }
    const title = reference.title?.trim() ?? "";
    return [
      {
        uri,
        title: title.length > 0 ? title : uri,
        excerpt: reference.excerpt?.trim() || null,
      },
    ];
  });
  return {
    query: searchQuery(toolCall.arguments),
    results,
    summary: toolCall.semanticOutput?.trim() || null,
  };
}
