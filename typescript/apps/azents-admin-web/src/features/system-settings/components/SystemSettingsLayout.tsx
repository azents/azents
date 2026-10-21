import { Box, Stack, Text, Title } from "@mantine/core";
import { SETTINGS_SECTIONS } from "@/shared/lib/admin-navigation";
import type { SystemSettingsLayoutProps } from "../containers/useSystemSettingsLayoutContainer";

export function SystemSettingsLayout({
  sections,
  activeSection,
}: SystemSettingsLayoutProps): React.ReactElement {
  return (
    <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw="72rem">
      {SETTINGS_SECTIONS.map(({ value, label, description }) => (
        <Box
          key={value}
          component="section"
          aria-label={label}
          style={activeSection === value ? {} : { display: "none" }}
        >
          <Stack gap="lg">
            <Stack gap="xs">
              <Title order={2}>{label}</Title>
              <Text size="sm" c="dimmed">
                {description}
              </Text>
              {value !== "audit" && (
                <Text size="xs" c="dimmed">
                  Switching settings sections keeps unsaved edits. Reloading or
                  leaving this page discards them.
                </Text>
              )}
            </Stack>
            {sections[value]}
          </Stack>
        </Box>
      ))}
    </Stack>
  );
}
