export const sessionPanelViews = [
  "files",
  "context",
  "subagents",
  "channels",
  "scheduled-tasks",
  "runtime",
  "metrics",
  "terminal",
  "system-prompt",
  "raw-events",
] as const;

export type SessionPanelView = (typeof sessionPanelViews)[number];

export function parseSessionPanelView(
  value: string | null,
): SessionPanelView | null {
  return sessionPanelViews.find((view) => view === value) ?? null;
}

export function getTabOverflow(
  scrollLeft: number,
  clientWidth: number,
  scrollWidth: number,
): { previous: boolean; next: boolean } {
  const position = Math.max(0, scrollLeft);
  return {
    previous: position > 1,
    next: position + clientWidth < scrollWidth - 1,
  };
}

export function sessionPanelHref(
  pathname: string,
  search: string,
  view: SessionPanelView | null,
): string {
  const params = new URLSearchParams(search);
  params.delete("page");
  params.delete("taskId");
  params.delete("edit");
  if (view !== null) {
    params.set("page", view);
  }
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}
