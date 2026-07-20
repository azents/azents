import assert from "node:assert/strict";
import test from "node:test";
import {
  groupToolActivityPhases,
  toolCallPresentation,
} from "./toolPresentationRegistry.ts";
import type { ToolActivityCall } from "./toolActivityPresentation.ts";

function clientCall(
  id: string,
  name: string,
  args: string,
  result: string | null = "ok",
): ToolActivityCall {
  return {
    type: "client",
    messageId: `message:${id}`,
    toolCall: {
      id,
      callId: id,
      name,
      arguments: args,
      status: "completed",
      ...(result === null ? {} : { result }),
    },
  };
}

void test("specializes validated inspection, execution, and change calls", () => {
  assert.equal(
    toolCallPresentation(
      clientCall("read", "read", JSON.stringify({ path: "/repo/a.ts" })),
    ).phaseKind,
    "inspection",
  );
  assert.equal(
    toolCallPresentation(
      clientCall(
        "exec",
        "functions.exec_command",
        JSON.stringify({ command: "pnpm test" }),
      ),
    ).phaseKind,
    "execution",
  );
  assert.equal(
    toolCallPresentation(
      clientCall(
        "edit",
        "edit",
        JSON.stringify({
          path: "/repo/a.ts",
          old_string: "before",
          new_string: "after",
        }),
      ),
    ).phaseKind,
    "changes",
  );
});

void test("falls back for malformed, unknown, and incomplete terminal shapes", () => {
  assert.equal(
    toolCallPresentation(clientCall("bad", "read", "{bad json")).type,
    "generic",
  );
  assert.equal(
    toolCallPresentation(clientCall("unknown", "custom.tool", "{}")).type,
    "generic",
  );
  assert.equal(
    toolCallPresentation(
      clientCall(
        "missing-result",
        "read",
        JSON.stringify({ path: "/repo/a.ts" }),
        null,
      ),
    ).type,
    "generic",
  );
});

void test("requires provider arguments to be a validated object", () => {
  const call: ToolActivityCall = {
    type: "provider",
    messageId: "message:code",
    toolCall: {
      id: "code-call",
      callId: "code-call",
      name: "code_interpreter",
      arguments: JSON.stringify("python"),
      status: "completed",
      output: "done",
    },
  };

  assert.equal(toolCallPresentation(call).type, "generic");
});

void test("contains adapter failures and falls back to generic", () => {
  const call = {
    type: "provider",
    messageId: "message:malformed-image",
    toolCall: {
      id: "malformed-image-call",
      callId: "malformed-image-call",
      name: "image_generation",
      arguments: JSON.stringify({ prompt: "A calm activity timeline" }),
      status: "completed",
      output: "Generated one image.",
      attachments: [
        {
          uri: "exchange://generated/malformed-image",
          mediaType: null,
        },
      ],
    },
  } as unknown as ToolActivityCall;

  assert.equal(toolCallPresentation(call).type, "generic");
});

void test("requires a prompt for client image generation", () => {
  assert.equal(
    toolCallPresentation(clientCall("image", "image_generation", "{}")).type,
    "generic",
  );
});

void test("promotes provider images with empty canonical input", () => {
  const call: ToolActivityCall = {
    type: "provider",
    messageId: "message:image",
    toolCall: {
      id: "image-call",
      callId: "image-call",
      name: "image_generation",
      arguments: "{}",
      status: "completed",
      output: "Generated one image.",
      attachments: [
        {
          attachmentId: "image-1",
          uri: "exchange://generated/image-1",
          mediaType: "image/png",
          name: "activity.png",
        },
        {
          attachmentId: "log-1",
          uri: "exchange://generated/log-1",
          mediaType: "text/plain",
          name: "generation.log",
        },
      ],
    },
  };

  const presentation = toolCallPresentation(call);
  assert.equal(presentation.type, "specialized");
  assert.equal(presentation.phaseKind, "generation");
  assert.deepEqual(
    presentation.deliverables.map((file) => file.attachmentId),
    ["image-1"],
  );
});

void test("groups only adjacent compatible phase kinds", () => {
  const calls = [
    clientCall("read-1", "read", JSON.stringify({ path: "/repo/a.ts" })),
    clientCall(
      "grep-1",
      "grep",
      JSON.stringify({ pattern: "A", path: "/repo" }),
    ),
    clientCall(
      "exec-1",
      "exec_command",
      JSON.stringify({ command: "pnpm test" }),
    ),
    clientCall("read-2", "read", JSON.stringify({ path: "/repo/b.ts" })),
  ];

  assert.deepEqual(
    groupToolActivityPhases(calls).map((phase) => [
      phase.kind,
      phase.calls.length,
    ]),
    [
      ["inspection", 2],
      ["execution", 1],
      ["inspection", 1],
    ],
  );
});
