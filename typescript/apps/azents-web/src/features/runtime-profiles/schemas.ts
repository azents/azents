import { z } from "zod/v4";

export const runtimeProfileFormSchema = z.object({
  displayName: z.string().trim().min(1).max(120),
  description: z.string().trim().max(1000),
  infrastructureProfileId: z.string().min(1),
  lifecycle: z.enum(["active", "disabled"]),
  allowedCidrs: z.string(),
  deniedCidrs: z.string(),
});

export type RuntimeProfileFormValues = z.infer<typeof runtimeProfileFormSchema>;
