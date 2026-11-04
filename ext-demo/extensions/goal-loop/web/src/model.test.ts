import { describe as suite, expect, it } from "vitest";
import { canResume, describe, EMPTY_VIEW, isWatched, parseView, rowView } from "./model";

const ITEM = {
  id: "acme/app/7",
  url: "https://github.com/acme/app/pull/7",
  label: "#7",
  title: "Fix login",
  toggle: "",
  status: "unmet",
  reason: "",
  note: "",
  wakes: 1,
  max_wakes: 10,
};

suite("parseView", () => {
  it("reads the server's view and drops malformed items", () => {
    const view = parseView(JSON.stringify({ v: 1, all: true, enabled: true, items: [ITEM, { id: 3 }] }));
    expect(view.all).toBe(true);
    expect(view.items).toHaveLength(1);
    expect(view.items[0].status).toBe("unmet");
  });

  it("treats unreadable values as empty", () => {
    expect(parseView("not json")).toEqual(EMPTY_VIEW);
    expect(parseView(null)).toEqual(EMPTY_VIEW);
  });
});

suite("isWatched", () => {
  it("lets a PR's own toggle override All PRs", () => {
    const view = parseView(JSON.stringify({ all: true, items: [{ ...ITEM, toggle: "off" }, ITEM] }));
    expect(view.items.map((item) => isWatched(view, item))).toEqual([false, true]);
  });
});

suite("describe", () => {
  it("shows the wakes used and why a goal ended", () => {
    const [item] = parseView(
      JSON.stringify({ items: [{ ...ITEM, status: "met", note: "#7 is green", wakes: 2 }] }),
    ).items;
    expect(describe(item)).toBe("Met · 2/10 wakes · #7 is green");
  });

  it("shows a paused goal as paused once, with how to resume it", () => {
    const note = "Paused by Stop — Resume to continue";
    const [item] = parseView(
      JSON.stringify({ items: [{ ...ITEM, status: "paused", reason: "stopped_by_user", note }] }),
    ).items;
    expect(item.status).toBe("paused");
    expect(describe(item)).toBe("Paused by Stop · 1/10 wakes · Resume to continue");
    expect(describe(item, true)).toBe(
      "Paused by Stop · 1/10 wakes · someone who can edit this session can resume it",
    );
  });
});

suite("canResume", () => {
  it("offers Resume only on paused goals", () => {
    const view = parseView(JSON.stringify({ items: [{ ...ITEM, status: "paused" }, ITEM] }));
    expect(view.items.map(canResume)).toEqual([true, false]);
  });
});

suite("rowView", () => {
  it("offers Resume on a paused goal to editors only, with matching text", () => {
    const [paused, running] = parseView(
      JSON.stringify({ items: [{ ...ITEM, status: "paused" }, ITEM] }),
    ).items;
    expect(rowView(paused, false)).toEqual({
      detail: "Paused by Stop · 1/10 wakes · Resume to continue",
      resume: true,
    });
    expect(rowView(paused, true)).toEqual({
      detail: "Paused by Stop · 1/10 wakes · someone who can edit this session can resume it",
      resume: false,
    });
    expect(rowView(running, false).resume).toBe(false);
  });
});
