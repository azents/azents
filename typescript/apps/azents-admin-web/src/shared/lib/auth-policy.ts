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

export function getNativePublicRouteUrl(
  baseUrl: string,
  routePath: string,
): string | null {
  if (getAuthCookiePath(baseUrl) === "/") {
    return null;
  }
  return getPublicRouteUrl(baseUrl, routePath);
}

function isPublicBasePath(baseUrl: string, pathname: string): boolean {
  const basePath = getAuthCookiePath(baseUrl);
  return (
    basePath === "/" ||
    pathname === basePath ||
    pathname.startsWith(`${basePath}/`)
  );
}

export function isPublicRouteUrl(
  baseUrl: string,
  currentUrl: string,
  routePath: string,
): boolean {
  try {
    const current = new URL(currentUrl);
    return (
      current.origin === new URL(baseUrl).origin &&
      current.pathname === getPublicRoutePath(baseUrl, routePath)
    );
  } catch {
    return false;
  }
}

export function getNativeLoginUrl(
  baseUrl: string,
  currentUrl: string,
): string | null {
  const loginUrl = getNativePublicRouteUrl(baseUrl, "/login");
  if (!loginUrl) {
    return null;
  }

  const current = new URL(currentUrl);
  if (isPublicRouteUrl(baseUrl, currentUrl, "/login")) {
    return null;
  }
  if (
    current.origin !== new URL(baseUrl).origin ||
    !isPublicBasePath(baseUrl, current.pathname)
  ) {
    return loginUrl;
  }

  const redirectUrl = new URL(loginUrl);
  redirectUrl.searchParams.set(
    "returnTo",
    `${current.pathname}${current.search}${current.hash}`,
  );
  return redirectUrl.toString();
}

export function getNativePostLoginUrl(
  baseUrl: string,
  currentUrl: string,
): string | null {
  const fallbackUrl = getNativePublicRouteUrl(baseUrl, "/workspaces");
  if (!fallbackUrl) {
    return null;
  }

  const current = new URL(currentUrl);
  const returnTo = current.searchParams.get("returnTo");
  if (!returnTo) {
    return fallbackUrl;
  }

  let target: URL;
  try {
    target = new URL(returnTo, current.origin);
  } catch {
    return fallbackUrl;
  }
  const loginPath = getPublicRoutePath(baseUrl, "/login");
  if (
    target.origin !== new URL(baseUrl).origin ||
    !isPublicBasePath(baseUrl, target.pathname) ||
    target.pathname === loginPath
  ) {
    return fallbackUrl;
  }
  return target.toString();
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
