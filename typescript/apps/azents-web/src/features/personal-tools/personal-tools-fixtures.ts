import type { PersonalToolkitResponse } from "@azents/public-client";

export function personalToolFixture(
  overrides: Partial<PersonalToolkitResponse> = {},
): PersonalToolkitResponse {
  return {
    id: "personal-example",
    toolkit_type: "mcp",
    slug: "research",
    name: "Personal research tools",
    description: null,
    config: {},
    prompt: null,
    has_credentials: true,
    enabled: true,
    always_expose_tools: false,
    created_at: "2026-10-17T00:00:00Z",
    updated_at: "2026-10-17T00:00:00Z",
    owner: {
      kind: "user",
      user_id: "example-owner",
      workspace_id: "workspace-id",
    },
    access_mode: "all",
    selected_agent_ids: [],
    readiness: "ready",
    ...overrides,
  };
}
