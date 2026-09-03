"use client";

/**
 * Avatar component for Agent.
 *
 * When `avatar` exists, render real image (thumbnail matching size or fallback to default),
 * otherwise render name hash-based color + initial with Mantine Avatar.
 */

import { Avatar } from "@mantine/core";
import type { UploadedImage } from "@azents/public-client";
import type { MantineColor } from "@mantine/core";

const AVATAR_COLORS: MantineColor[] = [
  "blue",
  "red",
  "green",
  "grape",
  "cyan",
  "teal",
  "pink",
  "orange",
  "violet",
  "indigo",
];

/** Derive color index deterministically from name */
function nameToColorIndex(name: string): number {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash + name.charCodeAt(i)) % AVATAR_COLORS.length;
  }
  return hash;
}

interface AgentAvatarProps {
  name: string;
  avatar?: UploadedImage | null;
  size?: number | "sm" | "md" | "lg";
  radius?: number | "sm" | "md" | "lg" | "xl";
}

/**
 * Select thumbnail tier by size: number means pixels, string maps to tier.
 * If tier is null (thumbnail not generated), fallback to default — always non-null.
 */
function pickThumbnailUrl(
  avatar: UploadedImage,
  size: AgentAvatarProps["size"],
): string {
  const tiers = avatar.thumbnails;
  const px = typeof size === "number" ? size : sizeToPx(size ?? "md");
  if (px <= 128 && tiers.small) {
    return tiers.small.url;
  }
  if (px <= 256 && tiers.medium) {
    return tiers.medium.url;
  }
  if (tiers.large) {
    return tiers.large.url;
  }
  return avatar.default.url;
}

function sizeToPx(size: "sm" | "md" | "lg"): number {
  switch (size) {
    case "sm":
      return 36;
    case "md":
      return 42;
    case "lg":
      return 56;
  }
}

export function AgentAvatar({
  name,
  avatar,
  size = "md",
  radius = "md",
}: AgentAvatarProps): React.ReactElement {
  if (avatar) {
    const src = pickThumbnailUrl(avatar, size);
    return (
      <Avatar src={src} alt={name} radius={radius} size={size}>
        {name.charAt(0).toUpperCase()}
      </Avatar>
    );
  }
  const color = AVATAR_COLORS[nameToColorIndex(name)];
  const initial = name.charAt(0).toUpperCase();
  return (
    <Avatar color={color} radius={radius} size={size}>
      {initial}
    </Avatar>
  );
}
