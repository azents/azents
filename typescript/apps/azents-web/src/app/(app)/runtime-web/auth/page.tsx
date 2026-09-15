import { notFound, redirect } from "next/navigation";
import { RuntimeWebAuthPage } from "@/features/runtime-web/RuntimeWebAuthPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export const revalidate = 0;

interface RuntimeWebAuthPageProps {
  searchParams: Promise<{ service_id?: string }>;
}

export default async function Page({
  searchParams,
}: RuntimeWebAuthPageProps): Promise<React.ReactElement> {
  const { service_id: serviceId } = await searchParams;
  if (serviceId == null || !/^[a-zA-Z0-9_-]{32}$/.test(serviceId)) {
    notFound();
  }
  const auth = await getInitialAuthState();
  if (auth.status === "unauthenticated") {
    const next = `/runtime-web/auth?service_id=${encodeURIComponent(serviceId)}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return <RuntimeWebAuthPage serviceId={serviceId} />;
}
