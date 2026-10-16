export interface BrowserTarget {
  task_id: string;
  page_id: string;
  resource_incarnation: string;
}

export const browserLinkKeys = [
  "browserTaskId",
  "browserPageId",
  "browserIncarnation",
] as const;

export function isBrowserSessionPath(pathname: string): boolean {
  return /^\/w\/[^/]+\/agents\/[^/]+\/sessions\/[^/]+\/?$/.test(pathname);
}

export type BrowserLinkedTarget =
  | { type: "NONE" }
  | { type: "INVALID" }
  | { type: "TARGET"; target: BrowserTarget };

export function parseBrowserTarget(search: string): BrowserLinkedTarget {
  const params = new URLSearchParams(search);
  const values = browserLinkKeys.map((key) => params.getAll(key));
  if (values.every((entries) => entries.length === 0)) {
    return { type: "NONE" };
  }
  if (
    values.some(
      (entries) =>
        entries.length !== 1 || !entries[0] || entries[0].length > 256,
    )
  ) {
    return { type: "INVALID" };
  }
  const task = params.get("browserTaskId");
  const page = params.get("browserPageId");
  const incarnation = params.get("browserIncarnation");
  if (!task || !page || !incarnation) {
    return { type: "INVALID" };
  }
  return {
    type: "TARGET",
    target: { task_id: task, page_id: page, resource_incarnation: incarnation },
  };
}

export function browserPanelHref(
  pathname: string,
  search: string,
  target: BrowserTarget,
): string {
  const params = new URLSearchParams(search);
  params.set("page", "browser");
  params.delete("taskId");
  params.delete("edit");
  params.set("browserTaskId", target.task_id);
  params.set("browserPageId", target.page_id);
  params.set("browserIncarnation", target.resource_incarnation);
  return `${pathname}?${params.toString()}`;
}

/** Extract only a current explicit page projection, never arbitrary result text. */
export function browserToolTarget(
  name: string,
  result: string | null,
): BrowserTarget | null {
  if (
    !["browser_open", "browser_observe", "browser_act"].includes(name) ||
    !result ||
    result.length > 1024 * 1024
  ) {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(result);
  } catch {
    return null;
  }
  if (
    typeof value !== "object" ||
    value === null ||
    !("page" in value) ||
    typeof value.page !== "object" ||
    value.page === null
  ) {
    return null;
  }
  const page = value.page;
  if (
    !("task_id" in page) ||
    !("id" in page) ||
    !("resource_incarnation" in page) ||
    typeof page.task_id !== "string" ||
    typeof page.id !== "string" ||
    typeof page.resource_incarnation !== "string" ||
    ![page.task_id, page.id, page.resource_incarnation].every(
      (field) => field.length > 0 && field.length <= 256,
    )
  ) {
    return null;
  }
  return {
    task_id: page.task_id,
    page_id: page.id,
    resource_incarnation: page.resource_incarnation,
  };
}
