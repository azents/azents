/**
 * Settings page route.
 *
 * /w/[handle]/settings → LLM Provider Integration management page
 */
import { LlmSettingsPage } from "@/features/llm-settings/LlmSettingsPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <LlmSettingsPage handle={handle} />;
}
