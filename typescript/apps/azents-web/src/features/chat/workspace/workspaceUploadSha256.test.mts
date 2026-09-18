import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { IncrementalSha256, sha256Hex } from "./workspaceUploadSha256.ts";

function nodeSha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

void test("hashes empty and short files with the standard SHA-256 vectors", () => {
  const empty = new Uint8Array();
  const abc = new TextEncoder().encode("abc");

  assert.equal(
    sha256Hex(empty),
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  );
  assert.equal(
    sha256Hex(abc),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
});

void test("places the length field in the correct final block", () => {
  for (const size of [55, 56, 63, 64, 65, 4 * 1024 * 1024 + 17]) {
    const value = new Uint8Array(size);
    value.fill(0x61);
    assert.equal(sha256Hex(value), nodeSha256(value), `size=${size}`);
  }
});

void test("supports incremental updates across arbitrary file slices", () => {
  const value = new Uint8Array(4097);
  for (let index = 0; index < value.length; index += 1) {
    value[index] = index % 251;
  }

  const hash = new IncrementalSha256();
  for (let offset = 0; offset < value.length; offset += 37) {
    hash.update(value.subarray(offset, Math.min(offset + 37, value.length)));
  }

  assert.equal(hash.digestHex(), nodeSha256(value));
});
