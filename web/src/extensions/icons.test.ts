import { PuzzleIcon, SearchIcon } from "lucide-react";
import { describe, expect, it } from "vitest";
import { extensionIcon } from "./icons";

describe("extensionIcon", () => {
  it("resolves supported names", () => {
    expect(extensionIcon("search")).toBe(SearchIcon);
  });

  it.each([null, "unknown", "constructor", "valueOf", "__proto__", "toString"])(
    "falls back to the puzzle icon for %s",
    (name) => {
      expect(extensionIcon(name)).toBe(PuzzleIcon);
    },
  );
});
