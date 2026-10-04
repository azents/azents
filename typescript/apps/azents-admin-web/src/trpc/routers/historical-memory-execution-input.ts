import { z } from "zod/v4";

export const historicalMemoryExecutionInputSchema = z.object({
  expectedVersion: z.number().int().nonnegative(),
  maxTurns: z.number().int().positive().nullable(),
  timeoutSeconds: z.number().int().positive(),
});
