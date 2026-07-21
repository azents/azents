"use client";

import { IconBook } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { ActivityRow } from "./ActivityRow";
import { SkillContentPanel } from "./SkillContentPanel";
import type { ReactElement } from "react";

interface SkillLoadedActivityRowProps {
  content: string;
  name: string | null;
}

export function SkillLoadedActivityRow({
  content,
  name,
}: SkillLoadedActivityRowProps): ReactElement {
  const t = useTranslations("chat");
  const displayName = name || t("skillLoaded.unknownSkill");
  const title = t("skillLoaded.title", { name: displayName });

  return (
    <ActivityRow
      ariaLabel={title}
      icon={<IconBook aria-hidden="true" size={14} stroke={1.8} />}
      primary={title}
      detail={<SkillContentPanel content={content} />}
    />
  );
}
