import { z } from "zod/v4";

const imageGenerationProjectionSchema = z.object({
  model: z
    .unknown()
    .optional()
    .transform((value) =>
      typeof value === "string" && value.trim().length > 0 ? value : null,
    ),
});
const imageGenerationWireSchema = z.record(z.string(), z.unknown());
const modelIdentifierSchema = z.string().nullable();

/** Compatibility decisions consume typed metadata, never opaque extension fields. */
export function builtinToolConfigHasSettings(value: unknown): boolean {
  return Object.keys(imageGenerationWireSchema.parse(value ?? {})).length > 0;
}

export type ImageGenerationConfigProjection = z.infer<
  typeof imageGenerationProjectionSchema
>;

/** Known selection is decoded once; provider-specific extension fields stay opaque. */
export function projectImageGenerationConfig(
  value: unknown,
): ImageGenerationConfigProjection {
  return imageGenerationProjectionSchema.parse(value ?? {});
}

/** Egress edits only model intent, preserving every opaque extension field. */
export function encodeImageGenerationModel(
  value: Record<string, unknown> | null,
  modelIdentifier: string | null,
): Record<string, unknown> {
  const result = { ...imageGenerationWireSchema.parse(value ?? {}) };
  const model = modelIdentifierSchema.parse(modelIdentifier);
  if (model === null) {
    delete result.model;
  } else {
    result.model = model;
  }
  return result;
}
