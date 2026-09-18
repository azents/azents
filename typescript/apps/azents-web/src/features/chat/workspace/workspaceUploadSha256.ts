/**
 * Small incremental SHA-256 implementation used by the upload worker.
 *
 * The browser Web Crypto API exposes one-shot digests only. Keeping the
 * incremental implementation in a separate module lets the worker hash
 * bounded file slices without materializing the complete File in memory.
 */

const ROUND_CONSTANTS = Uint32Array.from([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

function compressBlock(state: Uint32Array, block: Uint8Array): void {
  const words = new Uint32Array(64);
  for (let index = 0; index < 16; index += 1) {
    const offset = index * 4;
    words[index] =
      ((block[offset] ?? 0) << 24) |
      ((block[offset + 1] ?? 0) << 16) |
      ((block[offset + 2] ?? 0) << 8) |
      (block[offset + 3] ?? 0);
  }
  for (let index = 16; index < 64; index += 1) {
    const previous = words[index - 15] ?? 0;
    const previousTwo = words[index - 2] ?? 0;
    const smallSigma0 =
      rotateRight(previous, 7) ^ rotateRight(previous, 18) ^ (previous >>> 3);
    const smallSigma1 =
      rotateRight(previousTwo, 17) ^
      rotateRight(previousTwo, 19) ^
      (previousTwo >>> 10);
    words[index] =
      (words[index - 16] ?? 0) +
      smallSigma0 +
      (words[index - 7] ?? 0) +
      smallSigma1;
  }

  let a = state[0] ?? 0;
  let b = state[1] ?? 0;
  let c = state[2] ?? 0;
  let d = state[3] ?? 0;
  let e = state[4] ?? 0;
  let f = state[5] ?? 0;
  let g = state[6] ?? 0;
  let h = state[7] ?? 0;

  for (let index = 0; index < 64; index += 1) {
    const bigSigma1 =
      rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
    const choose = (e & f) ^ (~e & g);
    const temporary1 =
      h +
      bigSigma1 +
      choose +
      (ROUND_CONSTANTS[index] ?? 0) +
      (words[index] ?? 0);
    const bigSigma0 =
      rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
    const majority = (a & b) ^ (a & c) ^ (b & c);
    const temporary2 = bigSigma0 + majority;

    h = g;
    g = f;
    f = e;
    e = d + temporary1;
    d = c;
    c = b;
    b = a;
    a = temporary1 + temporary2;
  }

  state[0] = (state[0] ?? 0) + a;
  state[1] = (state[1] ?? 0) + b;
  state[2] = (state[2] ?? 0) + c;
  state[3] = (state[3] ?? 0) + d;
  state[4] = (state[4] ?? 0) + e;
  state[5] = (state[5] ?? 0) + f;
  state[6] = (state[6] ?? 0) + g;
  state[7] = (state[7] ?? 0) + h;
}

function writeUint32(output: Uint8Array, offset: number, value: number): void {
  output[offset] = (value >>> 24) & 0xff;
  output[offset + 1] = (value >>> 16) & 0xff;
  output[offset + 2] = (value >>> 8) & 0xff;
  output[offset + 3] = value & 0xff;
}

export class IncrementalSha256 {
  private readonly state = Uint32Array.from([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
    0x1f83d9ab, 0x5be0cd19,
  ]);

  private readonly buffer = new Uint8Array(64);

  private bufferLength = 0;

  private bytesHashed = 0;

  public update(data: Uint8Array): void {
    this.bytesHashed += data.byteLength;
    let offset = 0;

    if (this.bufferLength > 0) {
      const remaining = 64 - this.bufferLength;
      if (data.byteLength < remaining) {
        this.buffer.set(data, this.bufferLength);
        this.bufferLength += data.byteLength;
        return;
      }
      this.buffer.set(data.subarray(0, remaining), this.bufferLength);
      compressBlock(this.state, this.buffer);
      this.bufferLength = 0;
      offset = remaining;
    }

    while (offset + 64 <= data.byteLength) {
      compressBlock(this.state, data.subarray(offset, offset + 64));
      offset += 64;
    }

    if (offset < data.byteLength) {
      this.buffer.set(data.subarray(offset), 0);
      this.bufferLength = data.byteLength - offset;
    }
  }

  public digestHex(): string {
    const finalState = this.state.slice();
    const finalBlock = new Uint8Array(128);
    finalBlock.set(this.buffer.subarray(0, this.bufferLength));
    finalBlock[this.bufferLength] = 0x80;

    const bitLength = this.bytesHashed * 8;
    const highLength = Math.floor(bitLength / 0x100000000);
    const lowLength = bitLength >>> 0;
    const lengthOffset = this.bufferLength >= 56 ? finalBlock.length - 8 : 56;
    writeUint32(finalBlock, lengthOffset, highLength);
    writeUint32(finalBlock, lengthOffset + 4, lowLength);

    if (this.bufferLength >= 56) {
      compressBlock(finalState, finalBlock.subarray(0, 64));
      compressBlock(finalState, finalBlock.subarray(64, 128));
    } else {
      compressBlock(finalState, finalBlock.subarray(0, 64));
    }

    const digest = new Uint8Array(32);
    finalState.forEach((value, index) => {
      writeUint32(digest, index * 4, value);
    });
    return Array.from(digest, (value) =>
      value.toString(16).padStart(2, "0"),
    ).join("");
  }
}

export function sha256Hex(data: Uint8Array): string {
  const hash = new IncrementalSha256();
  hash.update(data);
  return hash.digestHex();
}
