export const markdownSample = `# Agent result

The run finished with **three** notable outcomes:

- Created a reusable Storybook provider
- Added isolated chat UI states
- Left backend calls out of the stories

\`pnpm run build-storybook\` should pass before publishing.

| State | Result |
| --- | --- |
| Loading | visible |
| Error | visible |
| Complete | visible |
`;

export const codeReadabilityMarkdownSample = `Inline code should stay readable: \`const threshold = Math.floor(maxInput * 0.9)\`.

\`\`\`ts
export function getCompactionThreshold(maxInput: number): number {
  const threshold = Math.floor(maxInput * 0.9);
  return threshold;
}
\`\`\`

\`\`\`json
{
  "theme": "light",
  "readability": true,
  "tokens": ["inline", "block"]
}
\`\`\`

\`\`\`
pnpm --filter @azents/web typecheck
\`\`\`
`;

export const mermaidMarkdownSample = `Here is the current handoff flow:

\`\`\`mermaid
sequenceDiagram
    participant User
    participant Web as azents-web
    participant API as Chat API
    participant Worker

    User->>Web: Send message
    Web->>API: Commit chat write
    API-->>Web: Return live snapshot
    API->>Worker: Wake session
    Worker-->>Web: Stream assistant response
\`\`\`
`;
