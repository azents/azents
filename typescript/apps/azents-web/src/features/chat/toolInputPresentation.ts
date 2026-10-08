export interface ToolInputField {
  name: string;
  text: string;
}

export type ToolInputPresentation =
  { type: "fields"; fields: ToolInputField[] } | { type: "text"; text: string };

/** Decode arbitrary diagnostic input into display-only fields at the boundary. */
export function toolInputPresentation(input: string): ToolInputPresentation {
  try {
    const value: unknown = JSON.parse(input);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return { type: "text", text: input };
    }
    return {
      type: "fields",
      fields: Object.entries(value).map(([name, field]: [string, unknown]) => ({
        name,
        text:
          typeof field === "string" && field.length > 0
            ? field
            : JSON.stringify(field, null, 2),
      })),
    };
  } catch {
    return { type: "text", text: input };
  }
}
