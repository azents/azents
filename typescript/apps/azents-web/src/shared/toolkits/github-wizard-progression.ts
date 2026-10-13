export type GitHubWizardStep =
  "IDENTITY" | "METHOD" | "CONNECTION" | "FEATURES" | "RUNTIME" | "REVIEW";
export const GITHUB_WIZARD_STEPS: GitHubWizardStep[] = [
  "IDENTITY",
  "METHOD",
  "CONNECTION",
  "FEATURES",
  "RUNTIME",
  "REVIEW",
];

export function wizardHeadingId(step: GitHubWizardStep): string {
  return `github-wizard-${step.toLowerCase()}`;
}
export function wizardScrollBehavior(reducedMotion: boolean): ScrollBehavior {
  return reducedMotion ? "auto" : "smooth";
}

/** Scroll the real nearest scroll viewport; a nested modal must not move the background page. */
export function revealGitHubWizardHeading(
  heading: HTMLElement,
  reducedMotion: boolean,
): void {
  heading.focus({ preventScroll: true });
  let viewport: HTMLElement | null = heading.parentElement;
  while (viewport != null) {
    const overflow = getComputedStyle(viewport).overflowY;
    if (
      (overflow === "auto" || overflow === "scroll") &&
      viewport.scrollHeight > viewport.clientHeight
    ) {
      break;
    }
    viewport = viewport.parentElement;
  }
  const margin =
    Number.parseFloat(getComputedStyle(heading).scrollMarginTop) || 0;
  const behavior = wizardScrollBehavior(reducedMotion);
  const dialogHeader = heading
    .closest('[role="dialog"]')
    ?.querySelector<HTMLElement>(".mantine-Modal-header");
  const pageHeader = document.querySelector<HTMLElement>(
    ".mantine-AppShell-header",
  );
  const header = dialogHeader ?? pageHeader;
  const headerBottom =
    header == null ? 0 : header.getBoundingClientRect().bottom;
  if (viewport != null) {
    const top = viewport.getBoundingClientRect().top;
    const obstruction = Math.max(0, headerBottom - top);
    viewport.scrollTo({
      top: Math.max(
        0,
        viewport.scrollTop +
          heading.getBoundingClientRect().top -
          top -
          obstruction -
          margin,
      ),
      behavior,
    });
    return;
  }
  window.scrollTo({
    top: Math.max(
      0,
      window.scrollY +
        heading.getBoundingClientRect().top -
        headerBottom -
        margin,
    ),
    behavior,
  });
}
