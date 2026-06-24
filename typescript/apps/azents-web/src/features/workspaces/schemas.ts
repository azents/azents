/**
 * Workspaces form validation schema
 */
import { z } from "zod/v4";

/** Workspace information */
export const workspaceSchema = z.object({
  workspaceName: z.string().min(1).max(50),
  workspaceHandle: z
    .string()
    .min(1)
    .max(30)
    .regex(/^[a-z0-9-]+$/),
  ownerName: z.string().min(1).max(50),
});

export type WorkspaceFormData = z.infer<typeof workspaceSchema>;
