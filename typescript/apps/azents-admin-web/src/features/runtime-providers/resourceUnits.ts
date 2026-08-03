export interface ResourceUnit<Unit extends string> {
  value: Unit;
  label: string;
  multiplier: number;
}

export const cpuUnits = [
  { value: "core", label: "core", multiplier: 1_000 },
  { value: "millicore", label: "millicore", multiplier: 1 },
] as const satisfies readonly ResourceUnit<string>[];

export const byteUnits = [
  { value: "GiB", label: "GiB", multiplier: 1_073_741_824 },
  { value: "MiB", label: "MiB", multiplier: 1_048_576 },
  { value: "KiB", label: "KiB", multiplier: 1_024 },
  { value: "bytes", label: "bytes", multiplier: 1 },
] as const satisfies readonly ResourceUnit<string>[];

export function resourceUnitForValue<Unit extends string>(
  value: number | null,
  units: readonly ResourceUnit<Unit>[],
): Unit {
  const defaultUnit = units[0];
  if (!defaultUnit) {
    throw new Error("A resource unit list must contain a default unit.");
  }
  if (value === null) {
    return defaultUnit.value;
  }

  for (const unit of units) {
    if (value % unit.multiplier === 0) {
      return unit.value;
    }
  }

  const smallestUnit = units[units.length - 1];
  if (!smallestUnit) {
    throw new Error("A resource unit list must contain a smallest unit.");
  }
  return smallestUnit.value;
}

export function resourceUnitByValue<Unit extends string>(
  value: string | null,
  units: readonly ResourceUnit<Unit>[],
): ResourceUnit<Unit> | null {
  return units.find((unit) => unit.value === value) ?? null;
}

export function resourceUnitValue<Unit extends string>(
  value: number | null,
  unit: ResourceUnit<Unit>,
): number | null {
  return value === null ? null : value / unit.multiplier;
}

export function baseResourceValue<Unit extends string>(
  value: number,
  unit: ResourceUnit<Unit>,
): number | null {
  const baseValue = value * unit.multiplier;
  return Number.isSafeInteger(baseValue) ? baseValue : null;
}
