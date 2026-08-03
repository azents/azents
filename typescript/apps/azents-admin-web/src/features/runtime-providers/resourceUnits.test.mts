import assert from "node:assert/strict";
import test from "node:test";
import {
  baseResourceValue,
  byteUnits,
  cpuUnits,
  resourceUnitByValue,
  resourceUnitForValue,
  resourceUnitValue,
} from "./resourceUnits.ts";

void test("CPU defaults to core and falls back to millicore when required", () => {
  assert.equal(resourceUnitForValue(null, cpuUnits), "core");
  assert.equal(resourceUnitForValue(2_000, cpuUnits), "core");
  assert.equal(resourceUnitForValue(1_500, cpuUnits), "millicore");
});

void test("byte values select the largest exactly divisible unit", () => {
  assert.equal(resourceUnitForValue(null, byteUnits), "GiB");
  assert.equal(resourceUnitForValue(21_474_836_480, byteUnits), "GiB");
  assert.equal(resourceUnitForValue(2_097_152, byteUnits), "MiB");
  assert.equal(resourceUnitForValue(1_500, byteUnits), "bytes");
});

void test("unit display and submission values preserve the base quantity", () => {
  const core = resourceUnitByValue("core", cpuUnits);
  const mib = resourceUnitByValue("MiB", byteUnits);

  assert.notEqual(core, null);
  assert.notEqual(mib, null);
  if (core === null || mib === null) {
    return;
  }

  assert.equal(resourceUnitValue(500, core), 0.5);
  assert.equal(baseResourceValue(0.5, core), 500);
  assert.equal(resourceUnitValue(1_572_864, mib), 1.5);
  assert.equal(baseResourceValue(1.5, mib), 1_572_864);
});

void test("inexact or unsafe input values are rejected", () => {
  const core = resourceUnitByValue("core", cpuUnits);
  const gib = resourceUnitByValue("GiB", byteUnits);

  assert.notEqual(core, null);
  assert.notEqual(gib, null);
  if (core === null || gib === null) {
    return;
  }

  assert.equal(baseResourceValue(0.0005, core), null);
  assert.equal(baseResourceValue(Number.MAX_SAFE_INTEGER, gib), null);
});
