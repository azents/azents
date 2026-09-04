import assert from "node:assert/strict";
import test from "node:test";
import { getAgentAvatarImageSource } from "./agentAvatarImageSource.ts";

const avatar = {
  filename: "avatar.png",
  default: {
    url: "https://images.example/avatar-large.webp",
    width: 512,
    height: 512,
  },
  thumbnails: {
    small: {
      url: "https://images.example/avatar-small.webp",
      width: 128,
      height: 128,
    },
    medium: {
      url: "https://images.example/avatar-medium.webp",
      width: 256,
      height: 256,
    },
    large: {
      url: "https://images.example/avatar-large.webp",
      width: 512,
      height: 512,
    },
  },
  uploaded_at: "2026-09-04T00:00:00Z",
};

void test("advertises density-aware sources for a large avatar", () => {
  assert.deepEqual(getAgentAvatarImageSource(avatar, 96), {
    src: "https://images.example/avatar-small.webp",
    srcSet:
      "https://images.example/avatar-small.webp 128w, " +
      "https://images.example/avatar-medium.webp 256w, " +
      "https://images.example/avatar-large.webp 512w",
    sizes: "6rem",
  });
});

void test("maps named Mantine sizes to their CSS pixel width", () => {
  assert.equal(getAgentAvatarImageSource(avatar, "md").sizes, "2.625rem");
});

void test("falls back to the default image when thumbnails are absent", () => {
  const source = getAgentAvatarImageSource(
    {
      ...avatar,
      thumbnails: {
        small: null,
        medium: null,
        large: null,
      },
    },
    96,
  );

  assert.deepEqual(source, {
    src: "https://images.example/avatar-large.webp",
  });
});
