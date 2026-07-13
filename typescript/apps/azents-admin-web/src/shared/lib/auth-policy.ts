export function getAuthCookiePath(baseUrl: string): string {
  const pathname = new URL(baseUrl).pathname;
  const normalized = pathname.replace(/\/$/, "");
  return normalized || "/";
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
