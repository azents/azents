"use client";

import { Grid, NumberInput, Select } from "@mantine/core";
import { useState } from "react";
import {
  BYTE_SIZE_UNITS,
  bytesInUnit,
  isByteSizeUnit,
  preferredByteSizeUnit,
  unitValueInBytes,
} from "../byteSize";
import type { ByteSizeUnit } from "../byteSize";

interface ByteSizeInputProps {
  label: string;
  description?: string;
  value: number | null;
  disabled: boolean;
  required?: boolean;
  placeholder?: string;
  onChange: (value: number | null) => void;
}

export function ByteSizeInput({
  label,
  description,
  value,
  disabled,
  required = false,
  placeholder,
  onChange,
}: ByteSizeInputProps): React.ReactElement {
  const [unit, setUnit] = useState<ByteSizeUnit>(() =>
    preferredByteSizeUnit(value),
  );

  return (
    <Grid align="flex-end">
      <Grid.Col span={8}>
        <NumberInput
          label={label}
          description={description}
          value={value === null ? "" : bytesInUnit(value, unit)}
          placeholder={placeholder}
          min={bytesInUnit(1, unit)}
          decimalScale={unit === "B" ? 0 : 10}
          withAsterisk={required}
          disabled={disabled}
          onChange={(nextValue) => onChange(unitValueInBytes(nextValue, unit))}
        />
      </Grid.Col>
      <Grid.Col span={4}>
        <Select
          label="Unit"
          data={[...BYTE_SIZE_UNITS]}
          value={unit}
          allowDeselect={false}
          disabled={disabled}
          onChange={(nextUnit) => {
            if (nextUnit !== null && isByteSizeUnit(nextUnit)) {
              setUnit(nextUnit);
            }
          }}
        />
      </Grid.Col>
    </Grid>
  );
}
