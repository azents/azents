import { redirect } from "next/navigation";
import { getPublicConfig } from "@/config";
import { getPublicRoutePath } from "@/shared/lib/auth-policy";

export default function Home(): never {
  redirect(getPublicRoutePath(getPublicConfig().publicBaseUrl, "/workspaces"));
}
