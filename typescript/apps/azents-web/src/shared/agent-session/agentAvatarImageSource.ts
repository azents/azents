import type { ImageFile, UploadedImage } from "@azents/public-client";

export type AgentAvatarSize = number | "sm" | "md" | "lg";

export interface AgentAvatarImageSource {
  src: string;
  srcSet?: string;
  sizes?: string;
}

/** Build responsive image attributes from the available avatar tiers. */
export function getAgentAvatarImageSource(
  avatar: UploadedImage,
  size: AgentAvatarSize,
): AgentAvatarImageSource {
  const displayWidth = typeof size === "number" ? size : sizeToPixels(size);
  const candidates = uniqueCandidates(avatar);
  const fallback =
    candidates.find((candidate) => candidate.width >= displayWidth) ??
    avatar.default;

  if (candidates.length < 2) {
    return { src: fallback.url };
  }

  return {
    src: fallback.url,
    srcSet: candidates
      .map((candidate) => `${candidate.url} ${candidate.width}w`)
      .join(", "),
    sizes: `${displayWidth / 16}rem`,
  };
}

function uniqueCandidates(avatar: UploadedImage): ImageFile[] {
  const candidates: ImageFile[] = [];
  const seenUrls = new Set<string>();
  for (const candidate of [
    avatar.thumbnails.small,
    avatar.thumbnails.medium,
    avatar.thumbnails.large,
    avatar.default,
  ]) {
    if (candidate && !seenUrls.has(candidate.url)) {
      candidates.push(candidate);
      seenUrls.add(candidate.url);
    }
  }
  return candidates;
}

function sizeToPixels(size: Exclude<AgentAvatarSize, number>): number {
  switch (size) {
    case "sm":
      return 36;
    case "md":
      return 42;
    case "lg":
      return 56;
  }
}
