import { getTranslations } from "next-intl/server";
import { GitHubAppGuidePage } from "@/features/github-app-guide/GitHubAppGuidePage";
import type { Metadata } from "next";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("githubAppGuide");
  return { title: t("title"), description: t("intro") };
}

export default function Page(): React.ReactElement {
  return <GitHubAppGuidePage />;
}
