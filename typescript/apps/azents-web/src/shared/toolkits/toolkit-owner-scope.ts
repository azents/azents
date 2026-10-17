import { z } from "zod/v4";

const workloadShape = {
  handle: z.string().min(1),
  agentId: z.string().min(1).optional(),
};
const accountShape = { owner: z.literal("user"), handle: z.string().min(1) };

type ScopedSchema<Fields extends z.ZodRawShape> = z.ZodUnion<
  [
    z.ZodObject<Fields & typeof workloadShape, z.core.$strict>,
    z.ZodObject<Fields & typeof accountShape, z.core.$strict>,
  ]
>;

/** Bind personal ownership to an explicit real Workspace without an owning Agent. */
export function toolkitScopedInput<Fields extends z.ZodRawShape>(
  fields: Fields,
): ScopedSchema<Fields> {
  return z.union([
    z.object({ ...fields, ...workloadShape }).strict(),
    z.object({ ...fields, ...accountShape }).strict(),
  ]);
}

export const toolkitOwnerScopeSchema = toolkitScopedInput({});
export type ToolkitOwnerScope = z.infer<typeof toolkitOwnerScopeSchema>;

const originSegment = z.string().regex(/^[A-Za-z0-9_-]+$/);
export const personalToolkitOriginSchema = z
  .object({
    handle: originSegment,
    agentId: originSegment,
    sessionId: originSegment.optional(),
  })
  .strict();
export type PersonalToolkitOrigin = z.infer<typeof personalToolkitOriginSchema>;

export function pickToolkitOwnerScope(
  scope: ToolkitOwnerScope,
): ToolkitOwnerScope {
  return "owner" in scope
    ? { owner: scope.owner, handle: scope.handle }
    : {
        handle: scope.handle,
        ...(scope.agentId != null && { agentId: scope.agentId }),
      };
}

/** Navigation identity is not authorization; the destination reauthorizes every read. */
export function toolkitManagementPath(
  scope: ToolkitOwnerScope,
  toolkitId: string | null,
  origin?: PersonalToolkitOrigin | null,
): string {
  if ("owner" in scope) {
    const base = `/w/${encodeURIComponent(scope.handle)}/personal-tools`;
    const path =
      toolkitId == null
        ? `${base}/new`
        : `${base}/${encodeURIComponent(toolkitId)}/edit`;
    const parsed = personalToolkitOriginSchema.safeParse(origin);
    if (!parsed.success || parsed.data.handle !== scope.handle) {
      return path;
    }
    const query = new URLSearchParams({
      originHandle: parsed.data.handle,
      originAgentId: parsed.data.agentId,
      ...(parsed.data.sessionId != null && {
        originSession: parsed.data.sessionId,
      }),
    });
    return `${path}?${query.toString()}`;
  }
  const handle = encodeURIComponent(scope.handle);
  if (scope.agentId != null) {
    return `/w/${handle}/agents/${encodeURIComponent(scope.agentId)}/settings/capabilities#agent-toolkits`;
  }
  return toolkitId == null
    ? `/w/${handle}/toolkits/new`
    : `/w/${handle}/toolkits/${encodeURIComponent(toolkitId)}/edit`;
}

/** Resume navigation is canonical identity, never an arbitrary return URL. */
export function isToolkitManagementPath(
  scope: ToolkitOwnerScope,
  toolkitId: string | null,
  path: string,
): boolean {
  if (path === toolkitManagementPath(scope, toolkitId)) {
    return true;
  }
  if (
    !("owner" in scope) ||
    !path.startsWith(`${toolkitManagementPath(scope, toolkitId)}?`)
  ) {
    return false;
  }
  const url = new URL(path, "https://navigation.invalid");
  const parsed = personalToolkitOriginSchema.safeParse({
    handle: url.searchParams.get("originHandle"),
    agentId: url.searchParams.get("originAgentId"),
    ...(url.searchParams.has("originSession") && {
      sessionId: url.searchParams.get("originSession"),
    }),
  });
  return (
    parsed.success &&
    path === toolkitManagementPath(scope, toolkitId, parsed.data)
  );
}

export function sameToolkitOwnerScope(
  left: ToolkitOwnerScope,
  right: ToolkitOwnerScope,
): boolean {
  if ("owner" in left || "owner" in right) {
    return "owner" in left && "owner" in right && left.handle === right.handle;
  }
  return left.handle === right.handle && left.agentId === right.agentId;
}
