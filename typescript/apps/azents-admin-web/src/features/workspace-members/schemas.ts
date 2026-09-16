import { z } from "zod";

/** Workspace member create and edit form validation schema. */
export const workspaceMemberFormSchema = z.object({
  userId: z.string().min(1, "User is required"),
  name: z.string().min(1, "Workspace display name is required").max(255),
  role: z.enum(["owner", "manager", "member"]),
});
