import { z } from "zod/v4";
import {
  googleServiceSchema,
  googleToolGroupSchema,
} from "./google-schemas.ts";
import {
  sameToolkitOwnerScope,
  toolkitScopedInput,
} from "./toolkit-owner-scope.ts";
import type { GoogleMetadata } from "./google-types.ts";
import type { ToolkitOwnerScope } from "./toolkit-owner-scope.ts";
import type {
  GoogleConnectionOutput,
  GoogleGroupDefinition,
  GoogleReview,
  GoogleService,
  GoogleToolGroup,
} from "@azents/public-client";

export const googleMetadataSchema = z
  .object({
    name: z.string().max(255),
    slug: z.string().max(100),
    description: z.string().max(20000),
    prompt: z.string().max(20000),
    enabled: z.boolean(),
    alwaysExposeTools: z.boolean(),
  })
  .strict();
export const googleDraftSchema = toolkitScopedInput({
  toolkitId: z.string().min(1).optional(),
  attemptId: z.string().min(1).optional(),
  expiresAt: z.string().datetime({ offset: true }),
  metadata: googleMetadataSchema,
  services: z.array(googleServiceSchema),
  toolGroups: z.array(googleToolGroupSchema),
  timeout: z.number().positive().max(300),
  revision: z.number().int().nonnegative().nullable(),
  baseline: z
    .object({
      services: z.array(googleServiceSchema),
      toolGroups: z.array(googleToolGroupSchema),
      timeout: z.number().positive().max(300),
    })
    .strict()
    .nullable(),
});
export type GoogleEditorDraft = z.infer<typeof googleDraftSchema>;
export const GOOGLE_DRAFT_KEY = "azents.google.editor";
export function deserializeGoogleDraft(
  value?: string,
): GoogleEditorDraft | null {
  if (!value) {
    return null;
  }
  try {
    const result = googleDraftSchema.safeParse(JSON.parse(value));
    return result.success ? result.data : null;
  } catch {
    return null;
  }
}
export function googleDraftMatches(
  draft: GoogleEditorDraft,
  scope: ToolkitOwnerScope,
  toolkitId?: string,
  attemptId?: string | null,
): boolean {
  return (
    sameToolkitOwnerScope(draft, scope) &&
    draft.toolkitId === toolkitId &&
    (draft.attemptId ?? null) === (attemptId ?? null) &&
    Date.parse(draft.expiresAt) > Date.now()
  );
}
export const emptyGoogleMetadata: GoogleMetadata = {
  name: "",
  slug: "",
  description: "",
  prompt: "",
  enabled: true,
  alwaysExposeTools: false,
};
export type GoogleReviewDecision =
  "NORMAL" | "ACCOUNT" | "PARTIAL" | "UNUSABLE";
/** Display identity is not sufficient: compare verified issuer and subject. */
export function googleReviewDecision(
  review: GoogleReview,
  saved: GoogleConnectionOutput | null,
  catalog: GoogleGroupDefinition[],
): GoogleReviewDecision {
  if (
    !review.can_confirm ||
    !review.renewable ||
    review.granted_scopes == null ||
    Date.parse(review.expires_at) <= Date.now()
  ) {
    return "UNUSABLE";
  }
  const groups = catalog.filter(
    (group) =>
      review.services.includes(group.service) &&
      review.tool_groups.includes(group.group),
  );
  if (
    groups.length === 0 ||
    !groups.some((group) =>
      group.operations.some((op) =>
        review.accesses
          .find((access) => access.service === group.service)
          ?.permitted_tools.includes(op),
      ),
    )
  ) {
    return "UNUSABLE";
  }
  if (
    saved?.identity != null &&
    (saved.identity.issuer !== review.identity.issuer ||
      saved.identity.subject !== review.identity.subject)
  ) {
    return "ACCOUNT";
  }
  return groups.every((group) =>
    group.operations.every((op) =>
      review.accesses
        .find((access) => access.service === group.service)
        ?.permitted_tools.includes(op),
    ),
  )
    ? "NORMAL"
    : "PARTIAL";
}
export function googleUsableSelection(
  review: GoogleReview,
  catalog: GoogleGroupDefinition[],
): { services: GoogleService[]; toolGroups: GoogleToolGroup[] } {
  const groups = catalog.filter(
    (group) =>
      review.services.includes(group.service) &&
      review.tool_groups.includes(group.group) &&
      group.operations.some((op) =>
        review.accesses
          .find((access) => access.service === group.service)
          ?.permitted_tools.includes(op),
      ),
  );
  return {
    services: [...new Set(groups.map((group) => group.service))],
    toolGroups: groups.map((group) => group.group),
  };
}
export function sameGoogleSelection(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return [...left].sort().join(",") === [...right].sort().join(",");
}

/** Rebase only explicit local selection edits, not rejected prior capabilities. */
export function reconcileGoogleSelection<T extends string>(
  baseline: T[],
  draft: T[],
  published: T[],
): T[] {
  const removed = new Set(baseline.filter((item) => !draft.includes(item)));
  return [
    ...new Set([
      ...published,
      ...draft.filter((item) => !baseline.includes(item)),
    ]),
  ].filter((item) => !removed.has(item));
}
