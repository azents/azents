export function shouldQueryProjectBrowserManifest(
  workspaceType: string | null,
): boolean {
  return workspaceType === "READY";
}
