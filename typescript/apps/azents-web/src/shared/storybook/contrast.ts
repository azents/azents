import { expect } from "storybook/test";

function relativeLuminance(color: string): number {
  const channels = color.match(/[\d.]+/g)?.map(Number);
  if (channels == null || channels.length !== 3) {
    throw new Error(`Expected an opaque computed RGB color, received ${color}`);
  }
  const linear = channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const [red, green, blue] = linear;
  if (red == null || green == null || blue == null) {
    throw new Error("Computed RGB channels are missing");
  }
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}

export async function expectReadableContrast(
  foreground: Element,
  background: Element = foreground,
): Promise<void> {
  const text = relativeLuminance(getComputedStyle(foreground).color);
  const fill = relativeLuminance(getComputedStyle(background).backgroundColor);
  const ratio = (Math.max(text, fill) + 0.05) / (Math.min(text, fill) + 0.05);
  await expect(
    ratio,
    foreground.textContent || foreground.tagName,
  ).toBeGreaterThanOrEqual(4.5);
}
