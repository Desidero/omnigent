import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_SIDEBAR_FOCUS,
  isSidebarFocusActive,
  readSidebarFocus,
  SIDEBAR_RECENCY_OPTIONS,
  sidebarRecencyOption,
  writeSidebarFocus,
} from "./sidebarFocusPreferences";

afterEach(() => {
  localStorage.clear();
});

describe("sidebarFocusPreferences", () => {
  it("defaults to no filter when nothing is stored", () => {
    expect(readSidebarFocus()).toEqual(DEFAULT_SIDEBAR_FOCUS);
    expect(isSidebarFocusActive(DEFAULT_SIDEBAR_FOCUS)).toBe(false);
  });

  it("round-trips both filters", () => {
    const focus = { needsMe: true, recency: "three-days" } as const;
    writeSidebarFocus(focus);
    expect(readSidebarFocus()).toEqual(focus);
    expect(isSidebarFocusActive(focus)).toBe(true);
  });

  it.each(["day", "week", "month"])("still loads the stored %s id", (recency) => {
    localStorage.setItem("omnigent:sidebar-focus", JSON.stringify({ needsMe: false, recency }));
    expect(readSidebarFocus()).toEqual({ needsMe: false, recency });
  });

  it("falls back per field on unknown or corrupt values", () => {
    localStorage.setItem(
      "omnigent:sidebar-focus",
      JSON.stringify({ needsMe: "yes", recency: "year" }),
    );
    expect(readSidebarFocus()).toEqual(DEFAULT_SIDEBAR_FOCUS);
    localStorage.setItem("omnigent:sidebar-focus", "{not json");
    expect(readSidebarFocus()).toEqual(DEFAULT_SIDEBAR_FOCUS);
  });

  it("orders the recency windows shortest first, with short labels for the chip", () => {
    expect(SIDEBAR_RECENCY_OPTIONS.map((option) => [option.id, option.shortLabel])).toEqual([
      ["any", null],
      ["day", "24h"],
      ["three-days", "3d"],
      ["week", "7d"],
      ["month", "30d"],
    ]);
    expect(sidebarRecencyOption("three-days")).toMatchObject({
      label: "Last 3 days",
      windowMs: 3 * 24 * 60 * 60 * 1000,
    });
  });
});
