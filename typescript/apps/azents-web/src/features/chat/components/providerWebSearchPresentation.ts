import type { ProviderToolCall } from "../types";

export interface ProviderWebSearchResult {
  excerpt: string | null;
  title: string;
  uri: string;
}

export interface ProviderWebSearchPresentation {
  queries: string[];
  results: ProviderWebSearchResult[];
  summary: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizedQuery(value: string): string | null {
  const query = value.replace(/\s+/gu, " ").trim();
  return query.length > 0 ? query : null;
}

function queryText(value: unknown): string | null {
  if (typeof value === "string") {
    return normalizedQuery(value);
  }
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.q === "string") {
    return normalizedQuery(value.q);
  }
  return typeof value.query === "string" ? normalizedQuery(value.query) : null;
}

function searchQueries(argumentsText: string): string[] {
  try {
    const value: unknown = JSON.parse(argumentsText);
    if (!isRecord(value)) {
      return [];
    }
    const candidates = Array.isArray(value.queries)
      ? value.queries
      : Object.hasOwn(value, "query")
        ? [value.query]
        : [value];
    return candidates.reduce<string[]>((queries, candidate) => {
      const query = queryText(candidate);
      return query !== null && !queries.includes(query)
        ? [...queries, query]
        : queries;
    }, []);
  } catch {
    return [];
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
    queries: searchQueries(toolCall.arguments),
    results,
    summary: toolCall.semanticOutput?.trim() || null,
  };
}
