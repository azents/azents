import { notFound, redirect } from "next/navigation";
import { getServerConfig } from "@/config/server";
import { RuntimeWebAuthPage } from "@/features/runtime-web/RuntimeWebAuthPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";
import { runtimeWebReturnTarget } from "@/shared/lib/runtime-web-return-target";

export const revalidate = 0;

interface RuntimeWebAuthPageProps {
  searchParams: Promise<{ service_id?: string; return_to?: string }>;
}

export default async function Page({
  searchParams,
}: RuntimeWebAuthPageProps): Promise<React.ReactElement> {
  const { service_id: serviceId, return_to: target } = await searchParams;
  const returnTarget = runtimeWebReturnTarget(target ?? "/");
  if (
    serviceId == null ||
    !/^[a-zA-Z0-9_-]{32}$/.test(serviceId) ||
    returnTarget === null
  ) {
    notFound();
  }
  const auth = await getInitialAuthState();
  if (auth.status === "unauthenticated") {
    const next = `/runtime-web/auth?${new URLSearchParams({ service_id: serviceId, return_to: returnTarget })}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return (
    <RuntimeWebAuthPage
      serviceId={serviceId}
      mainWebOrigin={getServerConfig().runtimeWebGatewayMainWebOrigin}
      returnTarget={returnTarget}
    />
  );
}
