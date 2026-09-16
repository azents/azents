import { redirect } from "next/navigation";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export default async function Page(): Promise<never> {
  const authState = await getInitialAuthState();

  redirect(authState.status === "authenticated" ? "/workspaces" : "/login");
}
