export const BYTE_SIZE_UNITS = ["B", "KiB", "MiB", "GiB"] as const;

export type ByteSizeUnit = (typeof BYTE_SIZE_UNITS)[number];

const BYTES_PER_UNIT: Record<ByteSizeUnit, number> = {
  B: 1,
  KiB: 1_024,
  MiB: 1_048_576,
  GiB: 1_073_741_824,
};

export function isByteSizeUnit(value: string): value is ByteSizeUnit {
  return BYTE_SIZE_UNITS.some((unit) => unit === value);
}

export function preferredByteSizeUnit(bytes: number | null): ByteSizeUnit {
  if (bytes === null) {
    return "GiB";
  }
  for (const unit of ["GiB", "MiB", "KiB"] satisfies ByteSizeUnit[]) {
    if (bytes % BYTES_PER_UNIT[unit] === 0) {
      return unit;
    }
  }
  return "B";
}

export function bytesInUnit(bytes: number, unit: ByteSizeUnit): number {
  return bytes / BYTES_PER_UNIT[unit];
}

export function unitValueInBytes(
  value: string | number,
  unit: ByteSizeUnit,
): number | null {
  if (typeof value !== "number") {
    return null;
  }
  return Math.round(value * BYTES_PER_UNIT[unit]);
}
