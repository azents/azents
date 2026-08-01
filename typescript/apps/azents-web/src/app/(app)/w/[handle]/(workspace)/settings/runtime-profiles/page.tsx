import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { RuntimeProfilesPage } from "@/features/runtime-profiles/RuntimeProfilesPage";
import { trpc } from "@/trpc/server";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  try {
    const workspace = await trpc.workspace.get({ handle });
    return <RuntimeProfilesPage handle={handle} workspace={workspace} />;
  } catch (error) {
    if (error instanceof TRPCError && error.code === "NOT_FOUND") {
      notFound();
    }
    throw error;
  }
}
