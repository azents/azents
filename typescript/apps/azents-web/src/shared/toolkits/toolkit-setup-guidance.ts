/** Presentation metadata only. The server catalog owns Provider availability. */
export const toolkitSetupGuides = {
  mcp: { docs: "https://modelcontextprotocol.io/docs/learn/client-concepts" },
  github: { docs: "https://docs.github.com/en/authentication" },
  google: { docs: "https://support.google.com/accounts/answer/13533235" },
  notion: { docs: "https://developers.notion.com/docs/mcp" },
  sentry: { docs: "https://docs.sentry.io/product/sentry-mcp/" },
  aws: {
    docs: "https://docs.aws.amazon.com/agent-toolkit/latest/userguide/security_iam_service-with-iam.html",
  },
  gcp: { docs: "https://cloud.google.com/iam/docs/keys-create-delete" },
  google_analytics: {
    docs: "https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart-client-libraries",
  },
  brave_search: { docs: "https://api-dashboard.search.brave.com/app/keys" },
  kubernetes: {
    docs: "https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/",
  },
  envvar: { docs: null },
  shell: { docs: null },
} satisfies Record<string, { docs: string | null }>;

export type ToolkitSetupGuide = keyof typeof toolkitSetupGuides;

export function getToolkitSetupGuide(
  type: string,
): ToolkitSetupGuide | "other" {
  switch (type) {
    case "mcp":
    case "github":
    case "google":
    case "notion":
    case "sentry":
    case "aws":
    case "gcp":
    case "google_analytics":
    case "brave_search":
    case "kubernetes":
    case "envvar":
    case "shell":
      return type;
    default:
      return "other";
  }
}
