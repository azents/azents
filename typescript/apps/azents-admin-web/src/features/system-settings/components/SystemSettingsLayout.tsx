import { Box, Grid, NavLink, Select, Stack, Text, Title } from "@mantine/core";
import { SETTINGS_SECTIONS } from "../settings-navigation";
import type { SystemSettingsLayoutProps } from "../containers/useSystemSettingsLayoutContainer";

export function SystemSettingsLayout({
  sections,
  activeSection,
  onSectionChange,
}: SystemSettingsLayoutProps): React.ReactElement {
  return (
    <Stack gap="lg" p="md" maw="80rem">
      <Stack gap="xs">
        <Title order={2}>System Settings</Title>
        <Text c="dimmed">
          Configure this Azents instance. Save changes in each section.
          Switching sections keeps unsaved edits; reloading or leaving this page
          does not.
        </Text>
      </Stack>
      <Grid gap="xl">
        <Grid.Col span={{ base: 12, sm: 3 }}>
          <Select
            hiddenFrom="sm"
            label="Settings section"
            value={activeSection}
            data={SETTINGS_SECTIONS.map(({ value, label }) => ({
              value,
              label,
            }))}
            onChange={onSectionChange}
            allowDeselect={false}
          />
          <Stack
            component="nav"
            aria-label="System Settings sections"
            gap="xs"
            visibleFrom="sm"
          >
            {SETTINGS_SECTIONS.map(({ value, label }) => (
              <NavLink
                key={value}
                component="button"
                type="button"
                label={label}
                active={activeSection === value}
                aria-current={activeSection === value ? "page" : false}
                onClick={() => onSectionChange(value)}
              />
            ))}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 9 }} style={{ minWidth: 0 }}>
          {SETTINGS_SECTIONS.map(({ value, label, description }) => (
            <Box
              key={value}
              component="section"
              aria-label={label}
              style={activeSection === value ? {} : { display: "none" }}
            >
              <Stack gap="lg">
                <Stack gap="xs">
                  <Title order={3}>{label}</Title>
                  <Text size="sm" c="dimmed">
                    {description}
                  </Text>
                </Stack>
                {sections[value]}
              </Stack>
            </Box>
          ))}
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
