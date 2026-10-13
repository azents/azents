export function usesToolkitCreationWizard(toolkitType: string): boolean {
  return toolkitType === "github" || toolkitType === "google";
}
/** Google configuration is confirmed by its reconnect lifecycle, independently of metadata edits. */
export function metadataProviderFields(
  toolkitType: string,
  config: Record<string, unknown>,
): { config?: Record<string, unknown> } {
  return toolkitType === "google" ? {} : { config };
}
