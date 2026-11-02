import { describe, expect, it } from "vitest";
import { readInvocationContext } from "../../../sdks/web-extension/src/protocol";

describe("readInvocationContext", () => {
  it("accepts hosts that send no invocation context", () => {
    expect(readInvocationContext(undefined)).toEqual({});
  });

  it("freezes a string record", () => {
    const context = readInvocationContext({ conversationId: "conv_123" });
    expect(context).toEqual({ conversationId: "conv_123" });
    expect(Object.isFrozen(context)).toBe(true);
  });

  it.each([null, "conv_123", ["conv_123"], { conversationId: 123 }])(
    "rejects a malformed context: %j",
    (value) => {
      expect(readInvocationContext(value)).toBeNull();
    },
  );
});
