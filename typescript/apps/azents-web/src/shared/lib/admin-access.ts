export function getAdminWebUrl(
  configuredUrl: string | null,
  systemRoles: readonly string[],
): string | null {
  if (!configuredUrl || !systemRoles.includes("system_admin")) {
    return null;
  }
  return configuredUrl;
}
