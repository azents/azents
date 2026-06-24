"use client";

/** Page footer — product/company/legal links and locale switch */
import { Anchor, Box, Container, Group, rem, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { AppLogo } from "@/shared/components/AppLogo";
import { LocaleSwitcher } from "./LocaleSwitcher";

/** Link list inside footer column */
interface FooterColumn {
  title: string;
  links: Array<{ label: string; href: string }>;
}

export function PageFooter(): React.ReactElement {
  const t = useTranslations("footer");
  const year = new Date().getFullYear();

  const columns: FooterColumn[] = [
    {
      title: t("product"),
      links: [
        { label: t("features"), href: "#" },
        { label: t("pricing"), href: "#" },
        { label: t("docs"), href: "#" },
      ],
    },
    {
      title: t("company"),
      links: [
        { label: t("about"), href: "#" },
        { label: t("blog"), href: "#" },
        { label: t("careers"), href: "#" },
      ],
    },
    {
      title: t("legal"),
      links: [
        { label: t("privacy"), href: "#" },
        { label: t("terms"), href: "#" },
      ],
    },
  ];

  return (
    <Box
      component="footer"
      style={{
        backgroundColor: "var(--mantine-color-body)",
        borderTop: "1px solid var(--mantine-color-default-border)",
        paddingTop: "var(--mantine-spacing-4xl)",
        paddingBottom: "var(--mantine-spacing-2xl)",
      }}
    >
      <Container size="lg">
        <Box
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: "var(--mantine-spacing-2xl)",
            marginBottom: "var(--mantine-spacing-3xl)",
          }}
        >
          {columns.map((col) => (
            <Stack key={col.title} gap="sm">
              {/* Column title — automatically inherits theme text color */}
              <Text fw={600} style={{ fontSize: rem(15) }}>
                {col.title}
              </Text>
              {/* Link — color switches via CSS hover */}
              {col.links.map((link) => (
                <Anchor
                  key={link.label}
                  href={link.href}
                  underline="never"
                  className="footer-link"
                  style={{ fontSize: rem(15) }}
                >
                  {link.label}
                </Anchor>
              ))}
            </Stack>
          ))}
        </Box>

        {/* Bottom: brand + locale switch + copyright */}
        <Group justify="space-between" align="center">
          <Group gap="md">
            <AppLogo />
            <LocaleSwitcher />
          </Group>
          {/* copyright — displayed with dimmed color */}
          <Text c="dimmed" style={{ fontSize: rem(13) }}>
            {t("copyright", { year: String(year) })}
          </Text>
        </Group>
      </Container>
    </Box>
  );
}
