"use client";

/**
 * Avatar component for Agent.
 *
 * When `avatar` exists, render responsive thumbnail sources matching CSS size and
 * display density. Otherwise render name hash-based color + initial with Mantine Avatar.
 */

import { Avatar } from "@mantine/core";
import {
  type AgentAvatarSize,
  getAgentAvatarImageSource,
} from "./agentAvatarImageSource";
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
  size?: AgentAvatarSize;
  radius?: number | "sm" | "md" | "lg" | "xl";
}

export function AgentAvatar({
  name,
  avatar,
  size = "md",
  radius = "md",
}: AgentAvatarProps): React.ReactElement {
  if (avatar) {
    const imageSource = getAgentAvatarImageSource(avatar, size);
    return (
      <Avatar
        src={imageSource.src}
        alt={name}
        radius={radius}
        size={size}
        imageProps={{
          srcSet: imageSource.srcSet,
          sizes: imageSource.sizes,
        }}
      >
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
