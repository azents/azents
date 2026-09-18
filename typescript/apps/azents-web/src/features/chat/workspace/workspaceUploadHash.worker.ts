/// <reference lib="webworker" />

import { IncrementalSha256 } from "./workspaceUploadSha256";

const HASH_CHUNK_SIZE = 4 * 1024 * 1024;

interface HashRequest {
  file: File;
}

type HashResponse =
  | { type: "progress"; loadedBytes: number; totalBytes: number }
  | { type: "done"; sha256: string };

async function hashFile(file: File): Promise<void> {
  const hash = new IncrementalSha256();
  let loadedBytes = 0;

  while (loadedBytes < file.size) {
    const nextBytes = Math.min(HASH_CHUNK_SIZE, file.size - loadedBytes);
    const buffer = await file
      .slice(loadedBytes, loadedBytes + nextBytes)
      .arrayBuffer();
    hash.update(new Uint8Array(buffer));
    loadedBytes += nextBytes;
    self.postMessage({
      type: "progress",
      loadedBytes,
      totalBytes: file.size,
    } satisfies HashResponse);
  }

  self.postMessage({
    type: "done",
    sha256: hash.digestHex(),
  } satisfies HashResponse);
}

self.onmessage = (event: MessageEvent<HashRequest>): void => {
  void hashFile(event.data.file);
};
