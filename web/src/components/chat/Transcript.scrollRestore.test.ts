import { describe, expect, it } from "vitest";
import {
  captureTranscriptViewSnapshot,
  holdAnchorRow,
  holdScrollDelta,
  resolveTranscriptViewOffset,
} from "./Transcript";

describe("transcript semantic scroll snapshots", () => {
  it("stores bottom as a mode instead of a pixel offset", () => {
    expect(
      captureTranscriptViewSnapshot({
        atBottom: true,
        scrollTop: 4200,
        anchor: { key: "user-8", start: 4000 },
      }),
    ).toEqual({ atBottom: true });
  });

  it("stores the visible bubble and its displacement from the viewport top", () => {
    expect(
      captureTranscriptViewSnapshot({
        atBottom: false,
        scrollTop: 4200,
        anchor: { key: "user-8", start: 4000 },
      }),
    ).toEqual({
      atBottom: false,
      anchorKey: "user-8",
      anchorOffset: -200,
      fallbackOffset: 4200,
    });
  });

  it("restores the same bubble after preceding row estimates change", () => {
    const snapshot = captureTranscriptViewSnapshot({
      atBottom: false,
      scrollTop: 4200,
      anchor: { key: "user-8", start: 4000 },
    });
    if (snapshot.atBottom) throw new Error("expected an anchor snapshot");

    expect(
      resolveTranscriptViewOffset(snapshot, (key) => (key === "user-8" ? 4600 : undefined)),
    ).toBe(4800);
  });

  it("uses the pixel fallback when the saved bubble is no longer loaded", () => {
    const snapshot = captureTranscriptViewSnapshot({
      atBottom: false,
      scrollTop: 4200,
      anchor: { key: "user-8", start: 4000 },
    });
    if (snapshot.atBottom) throw new Error("expected an anchor snapshot");

    expect(resolveTranscriptViewOffset(snapshot, () => undefined)).toBe(4200);
  });
});

describe("transcript read-position hold", () => {
  // Mounted rows as last held: 200px tall, 16px apart.
  const rows = [
    { key: "user-1", start: 0, end: 200 },
    { key: "assistant-1", start: 216, end: 416 },
    { key: "user-2", start: 432, end: 632 },
    { key: "assistant-2", start: 648, end: 848 },
  ];

  it("holds the first row fully inside the viewport", () => {
    expect(holdAnchorRow(rows, 100, 500)).toEqual(rows[1]);
    expect(holdAnchorRow(rows, 216, 500)).toEqual(rows[1]);
    expect(holdAnchorRow(rows, 217, 500)).toEqual(rows[2]);
  });

  it("falls back to the row crossing the viewport top when none fits", () => {
    // A reply taller than the viewport: the reader is inside it.
    const tall = [
      { key: "user-1", start: 0, end: 200 },
      { key: "assistant-1", start: 216, end: 3000 },
    ];
    expect(holdAnchorRow(tall, 500, 600)).toEqual(tall[1]);
    // The viewport top sits in the gap before a row taller than the viewport.
    expect(holdAnchorRow(tall, 205, 600)).toEqual(tall[1]);
  });

  it("holds nothing when no held row intersects the viewport", () => {
    // After a long jump the last held rows are all off-screen.
    expect(holdAnchorRow(rows, 5000, 500)).toBeUndefined();
    expect(holdAnchorRow([], 0, 500)).toBeUndefined();
  });

  it("moves by the held row's start, either way", () => {
    const anchor = rows[1]!;
    expect(holdScrollDelta(anchor, { ...anchor, start: 316, end: 516 }, false)).toBe(100);
    expect(holdScrollDelta(anchor, { ...anchor, start: 116, end: 316 }, false)).toBe(-100);
    expect(holdScrollDelta(anchor, anchor, false)).toBe(0);
  });

  it("holds a row a history page renamed by its bottom edge", () => {
    // The page grew the row at its top by 300 (the turn's earlier items) on
    // top of 1000 of older rows inserted above it.
    const anchor = rows[0]!;
    const grown = { ...anchor, start: 1000, end: 1500 };
    expect(holdScrollDelta(anchor, grown, true)).toBe(1300);
    expect(holdScrollDelta(anchor, grown, false)).toBe(1000);
  });

  it("holds nothing when the held row is gone", () => {
    expect(holdScrollDelta(rows[1]!, undefined, false)).toBeUndefined();
  });
});
