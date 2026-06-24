"use client";

/**
 * Shell tool settings form fields.
 *
 * Input allowed_domains / denied_domains with TagsInput.
 */

import { Stack, TagsInput, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import type { ShellConfigValues } from "../schemas";

interface ShellConfigFieldsProps {
  value: ShellConfigValues;
  onChange: (value: ShellConfigValues) => void;
}

export function ShellConfigFields({
  value,
  onChange,
}: ShellConfigFieldsProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits");

  return (
    <Stack gap="sm">
      <div>
        <TagsInput
          label={t("allowedDomainsLabel")}
          placeholder={t("allowedDomainsPlaceholder")}
          value={value.allowed_domains}
          onChange={(v) => onChange({ ...value, allowed_domains: v })}
          clearable
        />
        <Text size="xs" c="dimmed" mt={4}>
          {t("allowedDomainsDescription")}
        </Text>
      </div>
      <div>
        <TagsInput
          label={t("deniedDomainsLabel")}
          placeholder={t("deniedDomainsPlaceholder")}
          value={value.denied_domains}
          onChange={(v) => onChange({ ...value, denied_domains: v })}
          clearable
        />
        <Text size="xs" c="dimmed" mt={4}>
          {t("deniedDomainsDescription")}
        </Text>
      </div>
    </Stack>
  );
}
