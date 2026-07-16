import type { ProviderToolCall } from "../types";

const SEMANTIC_NAMES: Record<string, string> = {
  code_interpreter: "Code interpreter",
  file_search: "File search",
  image_generation: "Image generation",
  mcp: "Connected tool",
  web_search: "Web search",
};

const RUNNING_LABELS: Record<string, string> = {
  code_interpreter: "Running code",
  file_search: "Searching files",
  image_generation: "Generating an image",
  mcp: "Using a connected tool",
  web_search: "Searching the web",
};

export function providerToolDisplayName(name: string): string {
  const knownName = SEMANTIC_NAMES[name];
  if (typeof knownName === "string") {
    return knownName;
  }
  const normalized = name.replaceAll("_", " ").trim();
  if (normalized.length === 0) {
    return "Provider tool";
  }
  return `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}`;
}

export function providerToolActivityLabel(toolCall: ProviderToolCall): string {
  const displayName = providerToolDisplayName(toolCall.name);
  switch (toolCall.status) {
    case "running":
      return (
        RUNNING_LABELS[toolCall.name] ?? `Running ${displayName.toLowerCase()}`
      );
    case "completed":
      return `${displayName} completed`;
    case "failed":
      return `${displayName} failed`;
    case "unknown":
      return "Provider tool activity";
  }
}

export function providerToolStatusLabel(
  status: ProviderToolCall["status"],
): string {
  switch (status) {
    case "running":
      return "Running";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "unknown":
      return "Status unavailable";
  }
}
