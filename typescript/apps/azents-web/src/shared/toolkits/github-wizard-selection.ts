import type {
  GitHubWizardAvailability,
  GitHubWizardIdentity,
  GitHubWizardMode,
} from "./github-wizard-state";

/** Only authoritative completed choice sets qualify; loading and failure never imply a sole option. */
export function soleGitHubChoice(
  state: "READY" | "LOADING" | "ERROR",
  choices: readonly string[],
  explicitlyChanged = false,
): string | null {
  return state === "READY" && choices.length === 1 && !explicitlyChanged
    ? (choices[0] ?? null)
    : null;
}

export function soleGitHubMethod(
  identity: GitHubWizardIdentity | null,
  availability: GitHubWizardAvailability,
): GitHubWizardMode | null {
  if (
    identity !== "APP" ||
    availability.type !== "READY" ||
    availability.installation === "configured"
  ) {
    return null;
  }
  return "github_app";
}
