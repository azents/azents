import { z } from "zod/v4";
import { isRecord } from "../lib/unknown-value.ts";

const serviceAccountIdentitySchema = z.object({
  client_email: z.string().refine((value) => Boolean(value)),
});
// Credential material is forwarded verbatim; only the consumed identity is decoded.
const serviceAccountKeySchema = z
  .custom<Record<string, unknown>>(isRecord)
  .refine((value) => serviceAccountIdentitySchema.safeParse(value).success);
/** Preserve the existing provider form's accepted Service Account key shape. */
export function getServiceAccountKey(
  value: unknown,
): Record<string, unknown> | null {
  const result = serviceAccountKeySchema.safeParse(value);
  return result.success ? result.data : null;
}
