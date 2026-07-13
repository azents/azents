export function getAuthCookiePath(baseUrl: string): string {
  const pathname = new URL(baseUrl).pathname;
  const normalized = pathname.replace(/\/$/, "");
  return normalized || "/";
}

export function getPublicRoutePath(baseUrl: string, routePath: string): string {
  const basePath = getAuthCookiePath(baseUrl);
  const normalizedRoute = routePath.replace(/^\/+/, "");
  return `${basePath === "/" ? "" : basePath}/${normalizedRoute}`;
}

export function getPublicRouteUrl(baseUrl: string, routePath: string): string {
  return new URL(getPublicRoutePath(baseUrl, routePath), baseUrl).toString();
}

export function isExpectedOrigin(
  origin: string | null,
  baseUrl: string,
): boolean {
  if (!origin) {
    return false;
  }
  try {
    return new URL(origin).origin === new URL(baseUrl).origin;
  } catch {
    return false;
  }
}
