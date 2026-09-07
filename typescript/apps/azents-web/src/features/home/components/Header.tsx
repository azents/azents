"use client";

/**
 * Landing page header component.
 *
 * Fixed header that transitions from transparent to blurred background based on scroll position.
 * Left "azents" wordmark, right CTA button layout.
 */
import { Button, Container, Group, rem } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AppLogo } from "@/shared/components/AppLogo";

/** Scroll detection threshold (px) */
const SCROLL_THRESHOLD = 50;

/** Landing page fixed header — switches to blur background on scroll */
export function Header(): React.ReactElement {
  const t = useTranslations("nav");
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    /** Update header background state based on scroll position */
    function handleScroll(): void {
      setScrolled(window.scrollY > SCROLL_THRESHOLD);
    }

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  return (
    <header
      style={{
        position: "fixed",
        left: 0,
        right: 0,
        top: 0,
        zIndex: 1000,
        background: scrolled
          ? "color-mix(in srgb, var(--mantine-color-body) 80%, transparent)"
          : "transparent",
        backdropFilter: scrolled ? "blur(12px)" : "none",
        transition: "background 0.3s ease, backdrop-filter 0.3s ease",
      }}
    >
      <Container size="lg">
        <Group justify="space-between" align="center" h={rem(64)}>
          {/* Logo wordmark — automatically inherits theme text color */}
          <AppLogo />

          {/* Navigation button — filled variant + auto-contrast handles color automatically */}
          <Group gap="sm">
            <Button component={Link} href="/login?next=/workspaces" radius="xl">
              {t("startWithEmail")}
            </Button>
          </Group>
        </Group>
      </Container>
    </header>
  );
}
