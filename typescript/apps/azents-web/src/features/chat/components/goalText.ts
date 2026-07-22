/** Convert a Goal Markdown objective into one normalized preview line. */

export function normalizeGoalPreviewText(objective: string): string {
  return objective
    .replace(/\r\n?/gu, "\n")
    .replace(/<!--[\s\S]*?-->/gu, " ")
    .replace(/!\[([^\]\n]*)\]\([^)]+\)/gu, "$1")
    .replace(/!\[([^\]\n]*)\]\[[^\]\n]*\]/gu, "$1")
    .replace(/\[([^\]\n]+)\]\([^)]+\)/gu, "$1")
    .replace(/\[([^\]\n]+)\]\[[^\]\n]*\]/gu, "$1")
    .replace(/^\s*\[[^\]\n]+\]:\s+\S+.*$/gmu, " ")
    .replace(/<((?:https?:\/\/|mailto:)[^ >]+)>/gu, "$1")
    .replace(/<\/?[A-Za-z][^>]*>/gu, " ")
    .replace(/```[^\n]*\n?/gu, "")
    .replace(/`([^`]+)`/gu, "$1")
    .replace(/^\s{0,3}(?:[-*_])(?:\s*[-*_]){2,}\s*$/gmu, " ")
    .replace(/^\s{0,3}#{1,6}\s+/gmu, "")
    .replace(/^\s{0,3}>\s?/gmu, "")
    .replace(/^\s{0,3}(?:[-+*]|\d+[.)])\s+(?:\[[ xX]\]\s+)?/gmu, "")
    .replace(/^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$/gmu, " ")
    .replace(/\|/gu, " ")
    .replace(/(\*\*|__)(?=\S)([^\n]*?\S)\1/gu, "$2")
    .replace(/(^|[^\w])([*_])(?=\S)([^\n]*?\S)\2/gmu, "$1$3")
    .replace(/~~(?=\S)([^\n]*?\S)~~/gu, "$1")
    .replace(/\\([\\`*_[\]{}()#+\-.!])/gu, "$1")
    .replace(/\s+/gu, " ")
    .trim();
}
