const LOGIN_REDIRECT_BASE = "https://login.azents.invalid";

export const DEFAULT_LOGIN_REDIRECT = "/workspaces";

export function getSafeLoginNext(target?: string | null): string | null {
  if (!target?.startsWith("/") || target.startsWith("//")) {
    return null;
  }

  const resolved = new URL(target, LOGIN_REDIRECT_BASE);
  return resolved.origin === LOGIN_REDIRECT_BASE ? target : null;
}

export function getPostLoginRedirect(target?: string | null): string {
  return getSafeLoginNext(target) ?? DEFAULT_LOGIN_REDIRECT;
}
