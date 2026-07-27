import assert from "node:assert/strict";
import test from "node:test";
import {
  bytesInUnit,
  preferredByteSizeUnit,
  unitValueInBytes,
} from "./byteSize.ts";

void test("empty byte sizes default to GiB", () => {
  assert.equal(preferredByteSizeUnit(null), "GiB");
});

void test("existing byte sizes use the largest exact unit up to GiB", () => {
  assert.equal(preferredByteSizeUnit(8 * 1_073_741_824), "GiB");
  assert.equal(preferredByteSizeUnit(1_610_612_736), "MiB");
  assert.equal(preferredByteSizeUnit(3_145_728), "MiB");
  assert.equal(preferredByteSizeUnit(3_072), "KiB");
  assert.equal(preferredByteSizeUnit(3_073), "B");
});

void test("byte size values convert in both directions", () => {
  assert.equal(bytesInUnit(8_589_934_592, "GiB"), 8);
  assert.equal(unitValueInBytes(1.5, "GiB"), 1_610_612_736);
  assert.equal(unitValueInBytes("", "GiB"), null);
});
