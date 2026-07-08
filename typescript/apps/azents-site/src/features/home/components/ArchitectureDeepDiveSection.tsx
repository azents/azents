"use client";

import { Carousel, type CarouselProps } from "@mantine/carousel";
import { Box, Container, Group, rem, Stack, Text, Title } from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { type KeyboardEvent, useRef, useState, type WheelEvent } from "react";
import classes from "./ArchitectureDeepDiveSection.module.css";
import { SectionHeader } from "./SectionHeader";

const SLIDES = [
  {
    id: "decoupledLoop",
    image: "/brand/azents/architecture-session-loop.png",
  },
  {
    id: "providers",
    image: "/brand/azents/architecture-runtime-providers.png",
  },
  {
    id: "longRunning",
    image: "/brand/azents/architecture-long-running.png",
  },
] as const;

type SlideId = (typeof SLIDES)[number]["id"];
type CarouselApi = Parameters<NonNullable<CarouselProps["getEmblaApi"]>>[0];

function ArchitectureSlide({
  image,
  index,
  slideId,
}: {
  image: string;
  index: number;
  slideId: SlideId;
}): React.ReactElement {
  const t = useTranslations("architectureDeepDive");

  return (
    <Box
      style={{
        background:
          "linear-gradient(180deg, rgba(21, 28, 39, 0.82), rgba(10, 15, 24, 0.92))",
        border: "1px solid rgba(148, 163, 184, 0.16)",
        borderRadius: rem(8),
        height: "100%",
        overflow: "hidden",
      }}
    >
      <Stack gap={0}>
        <Box
          style={{
            aspectRatio: "16 / 9",
            background: "#070a0f",
            overflow: "hidden",
            position: "relative",
          }}
        >
          <Image
            alt={t(`slides.${slideId}.imageAlt`)}
            fill
            priority={index === 0}
            sizes="(max-width: 768px) 92vw, 1160px"
            src={image}
            style={{
              objectFit: "cover",
            }}
          />
          <Box
            style={{
              background:
                "linear-gradient(180deg, rgba(10, 15, 24, 0) 58%, rgba(10, 15, 24, 0.86) 100%)",
              inset: 0,
              pointerEvents: "none",
              position: "absolute",
            }}
          />
        </Box>

        <Group
          align="start"
          gap="xl"
          justify="space-between"
          p={{ base: "xl", md: "3xl" }}
          pt={{ base: "lg", md: "2xl" }}
          style={{
            background:
              "linear-gradient(180deg, rgba(10, 15, 24, 0.96), rgba(10, 15, 24, 0.86))",
          }}
        >
          <Stack gap="sm" maw={rem(760)}>
            <Text
              c="var(--mantine-color-signal-2)"
              ff="monospace"
              fw={700}
              size="sm"
            >
              {t(`slides.${slideId}.eyebrow`)}
            </Text>
            <Title fz={{ base: rem(28), md: rem(40) }} lh={1.1} order={3}>
              <span className={classes.desktopTitle}>
                {t(`slides.${slideId}.title`)}
              </span>
              <span className={classes.mobileTitle}>
                {t(`slides.${slideId}.mobileTitle`)}
              </span>
            </Title>
            <Text c="dimmed" lh={1.65} size="lg">
              {t(`slides.${slideId}.body`)}
            </Text>
          </Stack>
          <Text c="dimmed" ff="monospace" size="sm">
            {String(index + 1).padStart(2, "0")} /{" "}
            {String(SLIDES.length).padStart(2, "0")}
          </Text>
        </Group>
      </Stack>
    </Box>
  );
}

export function ArchitectureDeepDiveSection(): React.ReactElement {
  const t = useTranslations("architectureDeepDive");
  const emblaRef = useRef<CarouselApi | null>(null);
  const lastWheelAtRef = useRef(0);
  const [activeIndex, setActiveIndex] = useState(0);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    const embla = emblaRef.current;
    if (!embla) {
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      embla.scrollPrev();
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      embla.scrollNext();
    }

    if (event.key === "Home") {
      event.preventDefault();
      embla.scrollTo(0);
    }

    if (event.key === "End") {
      event.preventDefault();
      embla.scrollTo(SLIDES.length - 1);
    }
  };

  const handleWheel = (event: WheelEvent<HTMLDivElement>): void => {
    const embla = emblaRef.current;
    if (!embla) {
      return;
    }

    const strongestDelta =
      Math.abs(event.deltaX) > Math.abs(event.deltaY)
        ? event.deltaX
        : event.deltaY;

    if (Math.abs(strongestDelta) < 28) {
      return;
    }

    event.preventDefault();

    const now = Date.now();
    if (now - lastWheelAtRef.current < 420) {
      return;
    }
    lastWheelAtRef.current = now;

    if (strongestDelta > 0) {
      embla.scrollNext();
    } else {
      embla.scrollPrev();
    }
  };

  return (
    <Box
      component="section"
      py={{ base: "4xl", md: "5xl" }}
      style={{ background: "#070a0f" }}
    >
      <Container size="xl">
        <Stack gap="3xl">
          <SectionHeader
            body={t("body")}
            eyebrow={t("eyebrow")}
            title={t("title")}
          />

          <Box
            aria-label={t("controls.keyboardLabel")}
            onKeyDown={handleKeyDown}
            role="region"
            style={{
              borderRadius: rem(8),
              outlineColor: "var(--mantine-color-signal-2)",
              outlineOffset: rem(8),
            }}
            tabIndex={0}
          >
            <Carousel
              controlSize={48}
              emblaOptions={{ align: "center", loop: true }}
              getEmblaApi={(embla) => {
                emblaRef.current = embla;
              }}
              getIndicatorProps={(index) => ({
                "aria-label": t("controls.goToSlide", {
                  slide: String(index + 1),
                }),
              })}
              includeGapInSize={false}
              onSlideChange={setActiveIndex}
              onWheel={handleWheel}
              slideGap="lg"
              slideSize="100%"
              styles={{
                container: {
                  cursor: "grab",
                },
                indicator: {
                  background:
                    "light-dark(var(--mantine-color-signal-6), var(--mantine-color-signal-2))",
                  height: rem(8),
                  transition: "width 180ms ease, opacity 180ms ease",
                  width: rem(8),
                },
                indicators: {
                  bottom: rem(-38),
                },
                root: {
                  paddingBottom: rem(42),
                },
              }}
              classNames={{
                control: classes.control,
                controls: classes.controls,
              }}
              nextControlIcon={<IconChevronRight size={24} />}
              previousControlIcon={<IconChevronLeft size={24} />}
              withIndicators
            >
              {SLIDES.map((slide, index) => (
                <Carousel.Slide key={slide.id}>
                  <ArchitectureSlide
                    image={slide.image}
                    index={index}
                    slideId={slide.id}
                  />
                </Carousel.Slide>
              ))}
            </Carousel>
          </Box>

          <Text c="dimmed" ff="monospace" size="xs" ta="center">
            {t("gestureHint", {
              current: String(activeIndex + 1).padStart(2, "0"),
              total: String(SLIDES.length).padStart(2, "0"),
            })}
          </Text>
        </Stack>
      </Container>
    </Box>
  );
}
