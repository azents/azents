import { WorkspaceSlackAppsPage } from "@/features/external-channel-workspace/WorkspaceSlackAppsPage";

type SlackAppsSearchParams = {
  connectionId?: string | string[];
  interactionId?: string | string[];
  interaction_id?: string | string[];
};

function firstQueryValue(value?: string | string[]): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ handle: string }>;
  searchParams: Promise<SlackAppsSearchParams>;
}): Promise<React.ReactElement> {
  const [{ handle }, query] = await Promise.all([params, searchParams]);
  const interactionId =
    firstQueryValue(query.interactionId) ??
    firstQueryValue(query.interaction_id);

  return (
    <WorkspaceSlackAppsPage
      handle={handle}
      initialConnectionId={firstQueryValue(query.connectionId)}
      interactionId={interactionId}
    />
  );
}
