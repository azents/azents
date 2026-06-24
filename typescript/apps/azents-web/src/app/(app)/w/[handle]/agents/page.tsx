/**
 * Legacy `/w/{handle}/agents` route — redirects to home (`/w/{handle}`).
 *
 * This route was removed when Home was reorganized as agent list. For bookmark/external
 * link compatibility, keep only redirect. Preserve search params such as `?role=`
 * to preserve filter state.
 */
import { redirect } from "next/navigation";

type ResolvedSearchParams = Record<string, string | string[] | null>;

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ handle: string }>;
  searchParams: Promise<ResolvedSearchParams>;
}): Promise<never> {
  const { handle } = await params;
  const resolved = await searchParams;

  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(resolved)) {
    if (value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const v of value) {
        query.append(key, v);
      }
    } else {
      query.set(key, value);
    }
  }

  const qs = query.toString();
  redirect(`/w/${handle}${qs ? `?${qs}` : ""}`);
}
