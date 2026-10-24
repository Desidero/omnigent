import { afterEach, describe, expect, it, vi } from "vitest";
import { isMobileViewport } from "./useIsMobileViewport";

function matchMediaStub(matches: (query: string) => boolean) {
  return (query: string) => ({
    matches: matches(query),
    addEventListener() {},
    removeEventListener() {},
  });
}

describe("isMobileViewport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is false where no media query can be asked", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(isMobileViewport()).toBe(false);
  });

  it("answers the shell's max-md breakpoint", () => {
    vi.stubGlobal(
      "matchMedia",
      matchMediaStub((query) => query === "(max-width: 767.98px)"),
    );
    expect(isMobileViewport()).toBe(true);
    vi.stubGlobal(
      "matchMedia",
      matchMediaStub(() => false),
    );
    expect(isMobileViewport()).toBe(false);
  });
});
