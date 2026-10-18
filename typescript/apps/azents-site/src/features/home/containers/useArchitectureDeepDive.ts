"use client";
import { useRef, useState } from "react";
import type { CarouselProps } from "@mantine/carousel";
import type { KeyboardEvent, WheelEvent } from "react";
type CarouselApi = Parameters<NonNullable<CarouselProps["getEmblaApi"]>>[0];
export interface ArchitectureDeepDiveProps {
  slideCount: number;
}
export interface ArchitectureDeepDiveViewProps extends ArchitectureDeepDiveProps {
  activeIndex: number;
  onSlideChange: (index: number) => void;
  getEmblaApi: (embla: CarouselApi) => void;
  handleKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  handleWheel: (event: WheelEvent<HTMLDivElement>) => void;
}
export function useArchitectureDeepDive(
  props: ArchitectureDeepDiveProps,
): ArchitectureDeepDiveViewProps {
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
      embla.scrollTo(props.slideCount - 1);
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
  return {
    ...props,
    activeIndex,
    onSlideChange: setActiveIndex,
    getEmblaApi: (embla) => {
      emblaRef.current = embla;
    },
    handleKeyDown,
    handleWheel,
  };
}
