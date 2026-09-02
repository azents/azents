import { z } from "zod/v4";

export const runtimeProfileFormSchema = z.object({
  displayName: z.string().trim().min(1).max(120),
  description: z.string().trim().max(1000),
  infrastructureProfileId: z.string().min(1),
  lifecycle: z.enum(["active", "disabled"]),
  terminalEnabled: z.boolean(),
  policySchemaVersion: z.union([z.literal(1), z.literal(2)]),
  networkMode: z.enum(["inherit", "direct", "proxy_required", "no_network"]),
  allowedCidrs: z.string(),
  deniedCidrs: z.string(),
  proxyDomainMode: z.enum(["unrestricted", "allowlist"]),
  allowedDomains: z.string(),
  deniedDomains: z.string(),
});

export type RuntimeProfileFormValues = z.infer<typeof runtimeProfileFormSchema>;
