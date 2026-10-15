export interface BrowserResource {
  handle: string;
  agentId: string;
  sessionId: string;
}

export function browserSocketUrl(
  base: string,
  resource: BrowserResource,
): string {
  const url = new URL(base);
  if (
    (url.protocol !== "https:" && url.protocol !== "http:") ||
    url.username ||
    url.password
  ) {
    throw new Error("Browser API origin must use HTTP or HTTPS.");
  }
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.search = "";
  url.hash = "";
  const parts = [resource.handle, resource.agentId, resource.sessionId].map(
    encodeURIComponent,
  );
  url.pathname = `${url.pathname.replace(/\/$/, "")}/browser/v1/workspaces/${parts[0]}/agents/${parts[1]}/sessions/${parts[2]}/ws`;
  return url.toString();
}
