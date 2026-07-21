"use client";

import { Box, rem, ScrollArea } from "@mantine/core";
import { IconBubble } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { ActivityRow } from "./ActivityRow";
import { activityDetailScrollbarSize } from "./activityRowPresentation";
import { MarkdownContent } from "./MarkdownContent";
import type { ReactElement } from "react";

interface ReasoningActivityRowProps {
  reasoningSummary: string;
}

const HTML_COMMENT_PATTERN =
  /<!--[\s\S]*?-->|<!—[\s\S]*?(?:—>|-->)|<!--|-->|<!—|—>/gu;

function removeHtmlComments(content: string): string {
  return content.replace(HTML_COMMENT_PATTERN, "");
}

function markdownLineToPlainText(line: string): string {
  return line
    .replace(/^(?:`{3,}|~{3,})[^`~]*$/u, "")
    .replace(/^(?:\s*[-*_]){3,}\s*$/u, "")
    .replace(/^\s*[-+*]\s+\[[ xX]\]\s+/u, "")
    .replace(/^\s{0,3}(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)/u, "")
    .replace(/!\[([^\]]*)\]\([^)]*\)/gu, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/\[([^\]]+)\]\[[^\]]*\]/gu, "$1")
    .replace(/<\/?[A-Za-z][^>]*>/gu, "")
    .replace(/<([^>]+)>/gu, "$1")
    .replace(/(\*\*|__|~~)(.*?)\1/gu, "$2")
    .replace(/(^|\s)([*_])([^*_]+)\2(?=\s|[.,!?]|$)/gu, "$1$3")
    .replace(/`([^`]*)`/gu, "$1")
    .replace(/\\([\\`*_{}\[\]()#+\-.!>])/gu, "$1")
    .replace(/&nbsp;/gu, " ")
    .replace(/&amp;/gu, "&")
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&quot;/gu, '"')
    .replace(/&#39;|&apos;/gu, "'")
    .replace(/\s+/gu, " ")
    .trim();
}

function getThinkingPreview(reasoningSummary: string): string | null {
  const firstNonEmptyLine = removeHtmlComments(reasoningSummary)
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .find((line) => line.length > 0);

  if (!firstNonEmptyLine) {
    return null;
  }

  const preview = markdownLineToPlainText(firstNonEmptyLine);
  return preview.length > 0 ? preview : null;
}

export function ReasoningActivityRow({
  reasoningSummary,
}: ReasoningActivityRowProps): ReactElement {
  const t = useTranslations("chat");
  const sanitizedReasoningSummary = useMemo(
    () => removeHtmlComments(reasoningSummary).trim(),
    [reasoningSummary],
  );
  const preview = useMemo(
    () => getThinkingPreview(sanitizedReasoningSummary),
    [sanitizedReasoningSummary],
  );
  const canExpand = sanitizedReasoningSummary.length > 0;
  const label = preview ?? t("thinkingLabel");
  const detail = canExpand ? (
    <ScrollArea.Autosize
      mah={rem(300)}
      scrollbarSize={activityDetailScrollbarSize}
    >
      <Box c="dimmed">
        <MarkdownContent>{sanitizedReasoningSummary}</MarkdownContent>
      </Box>
    </ScrollArea.Autosize>
  ) : null;

  return (
    <ActivityRow
      ariaLabel={label}
      collapseFromDetail
      detail={detail}
      detailAriaLabel={t("collapseThinking")}
      expandedPrimary={t("thinkingLabel")}
      icon={<IconBubble aria-hidden="true" size={14} stroke={1.8} />}
      primary={label}
    />
  );
}
