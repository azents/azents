function canonicalOrigin(value: string): string | null {
  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      (url.pathname !== "/" && url.pathname !== "") ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url.origin;
  } catch {
    return null;
  }
}

export function externalRequestOrigin(request: Request): string {
  const forwardedProtocol = request.headers.get("x-forwarded-proto");
  const forwardedHost =
    request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (
    forwardedProtocol !== null &&
    forwardedHost !== null &&
    !forwardedProtocol.includes(",") &&
    !forwardedHost.includes(",")
  ) {
    const forwardedOrigin = canonicalOrigin(
      `${forwardedProtocol}://${forwardedHost}`,
    );
    if (forwardedOrigin !== null) {
      return forwardedOrigin;
    }
  }
  return new URL(request.url).origin;
}

export function hasExactRequestOrigin(
  request: Request,
  allowedOrigin: string,
): boolean {
  const origin = request.headers.get("origin");
  const canonicalAllowed = canonicalOrigin(allowedOrigin);
  return (
    origin !== null && canonicalAllowed !== null && origin === canonicalAllowed
  );
}
