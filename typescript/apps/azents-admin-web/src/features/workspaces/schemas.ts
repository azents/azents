import { z } from "zod";

/**
 * Workspace 폼 유효성 검사 스키마
 */
export const workspaceFormSchema = z.object({
  name: z.string().min(1, "이름은 필수입니다"),
  handle: z
    .string()
    .min(1, "핸들은 필수입니다")
    .regex(/^[a-z0-9-]+$/, "핸들은 소문자, 숫자, 하이픈만 사용할 수 있습니다"),
});
