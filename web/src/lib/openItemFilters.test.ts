import { afterEach, describe, expect, it } from "vitest";
import {
  NO_OPEN_ITEM_FILTERS,
  filterOpenItemRows,
  groupOpenItemRows,
  openItemFacetCounts,
  readOpenItemsView,
  writeOpenItemsView,
} from "./openItemFilters";
import type { OpenItemRow } from "./openItems";

function row(label: string, fields: Partial<OpenItemRow> = {}): OpenItemRow {
  const kinds = { Q: "question", R: "risk", F: "finding", T: "follow_up" } as const;
  return {
    label,
    kind: kinds[label[0] as keyof typeof kinds] ?? null,
    status: "open",
    title: `Title ${label}`,
    detail: "",
    topic: null,
    stored: null,
    entry: null,
    recent: false,
    dismissed: false,
    ...fields,
  };
}

const ROWS = [
  row("Q1", { title: "Backfill window", topic: "cache" }),
  row("Q2", { status: "answered", detail: "Copy or drop soft-deleted rows?", topic: "cache" }),
  row("R1", { status: "closed", title: "Flaky CI" }),
  row("T1", { topic: "release", recent: true }),
  row("A4", { title: "Other letter" }),
];
const labels = (rows: readonly OpenItemRow[]) => rows.map((each) => each.label);

afterEach(() => {
  writeOpenItemsView("conv", { filters: NO_OPEN_ITEM_FILTERS, toggledGroups: [] });
});

describe("filterOpenItemRows", () => {
  it("searches label, title, detail and topic, every word", () => {
    const search = (query: string) =>
      labels(filterOpenItemRows(ROWS, { ...NO_OPEN_ITEM_FILTERS, query }));
    expect(search("backfill")).toEqual(["Q1"]);
    expect(search("SOFT-deleted")).toEqual(["Q2"]);
    expect(search("cache")).toEqual(["Q1", "Q2"]);
    expect(search("r1")).toEqual(["R1"]);
    expect(search("cache copy")).toEqual(["Q2"]);
    expect(search("  ")).toEqual(labels(ROWS));
  });

  it("keeps the rows of the selected status, kind and topic", () => {
    const only = (filters: Partial<typeof NO_OPEN_ITEM_FILTERS>) =>
      labels(filterOpenItemRows(ROWS, { ...NO_OPEN_ITEM_FILTERS, ...filters }));
    expect(only({ status: "answered" })).toEqual(["Q2"]);
    expect(only({ kind: "question" })).toEqual(["Q1", "Q2"]);
    expect(only({ kind: "other" })).toEqual(["A4"]);
    expect(only({ topic: "cache", status: "open" })).toEqual(["Q1"]);
  });
});

describe("openItemFacetCounts", () => {
  it("counts what each chip would list, under the search and the other chips", () => {
    expect(openItemFacetCounts(ROWS, NO_OPEN_ITEM_FILTERS)).toEqual({
      status: { open: 3, answered: 1, closed: 1 },
      kinds: [
        { kind: "question", count: 2 },
        { kind: "risk", count: 1 },
        { kind: "follow_up", count: 1 },
        { kind: "other", count: 1 },
      ],
      topics: [
        { topic: "cache", count: 2 },
        { topic: "release", count: 1 },
      ],
    });
    const cacheOnly = openItemFacetCounts(ROWS, { ...NO_OPEN_ITEM_FILTERS, topic: "cache" });
    expect(cacheOnly.status).toEqual({ open: 1, answered: 1, closed: 0 });
    // The topic facet itself still offers every topic.
    expect(cacheOnly.topics.map(({ topic }) => topic)).toEqual(["cache", "release"]);
  });
});

describe("groupOpenItemRows", () => {
  it("groups by status: the latest reply's items, then open, answered and closed (folded)", () => {
    expect(
      groupOpenItemRows(ROWS, "status").map((group) => [
        group.title,
        labels(group.rows),
        group.foldedByDefault,
      ]),
    ).toEqual([
      ["In the latest reply", ["T1"], false],
      ["Open", ["Q1", "A4"], false],
      ["Answered", ["Q2"], false],
      ["Closed", ["R1"], true],
    ]);
  });

  it("groups by topic, items without one last, open first within a group", () => {
    expect(
      groupOpenItemRows(ROWS, "topic").map((group) => [group.title, labels(group.rows)]),
    ).toEqual([
      ["cache", ["Q1", "Q2"]],
      ["release", ["T1"]],
      ["No topic", ["A4", "R1"]],
    ]);
  });

  it("groups by kind in label order, other letters last", () => {
    expect(groupOpenItemRows(ROWS, "kind").map((group) => group.title)).toEqual([
      "Questions",
      "Risks",
      "Follow-ups",
      "Other",
    ]);
  });
});

describe("the panel's view", () => {
  it("is kept per session until the page reloads", () => {
    const filters = { ...NO_OPEN_ITEM_FILTERS, query: "cache" };
    writeOpenItemsView("conv", { filters, toggledGroups: ["closed"] });
    expect(readOpenItemsView("conv")).toEqual({ filters, toggledGroups: ["closed"] });
    expect(readOpenItemsView("other").filters).toEqual(NO_OPEN_ITEM_FILTERS);
    expect(readOpenItemsView(null).filters).toEqual(NO_OPEN_ITEM_FILTERS);
  });
});
