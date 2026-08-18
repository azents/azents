import { z } from "zod";

/**
 * Workspace form validation schema
 */
export const workspaceFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  handle: z
    .string()
    .min(1, "Handle is required")
    .regex(
      /^[a-z0-9-]+$/,
      "Handle can contain only lowercase letters, numbers, and hyphens",
    ),
});
