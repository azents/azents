"use client";

import { useRouter } from "next/navigation";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ToolkitForm } from "@/shared/toolkits/components/ToolkitForm";
import { useToolkitFormContainer } from "@/shared/toolkits/containers/useToolkitFormContainer";
import { agentPersonalToolsPath } from "./navigation";
import type { PersonalToolsOrigin } from "./navigation";
import type { ToolkitFormProps } from "@/shared/toolkits/components/ToolkitForm";

function usePersonalToolkitFormContainer({
  handle,
  toolkitId,
  origin,
}: {
  handle: string;
  toolkitId?: string;
  origin: PersonalToolsOrigin | null;
}): ToolkitFormProps {
  const router = useRouter();
  const backPath =
    origin === null
      ? `/w/${encodeURIComponent(handle)}/personal-tools`
      : agentPersonalToolsPath(origin);
  const form = useToolkitFormContainer({
    owner: "user",
    handle,
    toolkitId,
    embedded: true,
    onComplete: () => router.push(backPath),
    navigationOrigin: origin ?? void 0,
  });
  return { ...form, embedded: false, backPath };
}

export const PersonalToolkitFormPage = createReactContainer(
  "PersonalToolkitFormPage",
  usePersonalToolkitFormContainer,
  ToolkitForm,
);
