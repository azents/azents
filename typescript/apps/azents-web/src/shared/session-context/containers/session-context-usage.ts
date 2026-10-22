export interface SessionContextUsage {
  totalTokens: number | null;
  promptTokens: number | null;
  completionTokens: number | null;
  reasoningTokens: number | null;
  cachedTokens: number | null;
  cacheCreationTokens: number | null;
}

/** Decode only consumed counters; other diagnostic fields remain opaque. */
export function projectSessionContextUsage(
  usage?: Record<string, unknown> | null,
): SessionContextUsage {
  return {
    totalTokens:
      typeof usage?.total_tokens === "number" ? usage.total_tokens : null,
    promptTokens:
      typeof usage?.prompt_tokens === "number" ? usage.prompt_tokens : null,
    completionTokens:
      typeof usage?.completion_tokens === "number"
        ? usage.completion_tokens
        : null,
    reasoningTokens:
      typeof usage?.reasoning_tokens === "number"
        ? usage.reasoning_tokens
        : null,
    cachedTokens:
      typeof usage?.cached_tokens === "number" ? usage.cached_tokens : null,
    cacheCreationTokens:
      typeof usage?.cache_creation_tokens === "number"
        ? usage.cache_creation_tokens
        : null,
  };
}
