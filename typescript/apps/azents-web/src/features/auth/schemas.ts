/**
 * Auth form validation schema
 */
import { z } from "zod/v4";

/** Email input */
export const emailSchema = z.object({
  email: z.string().email(),
});

export type EmailFormData = z.infer<typeof emailSchema>;

/** Verification code input */
export const verifySchema = z.object({
  code: z
    .string()
    .length(6)
    .regex(/^[A-Z0-9]+$/),
});

export type VerifyFormData = z.infer<typeof verifySchema>;
