import { afterEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch: fetchMock }));

import {
  buildItemLabelIndex,
  itemLabelsIn,
  struckItemLabelsIn,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import {
  chatResolution,
  compareItemLabels,
  countOpenRows,
  fetchStoredOpenItems,
  mergeStoredOpenItems,
  openItemRows,
  storedItemOf,
  withWrittenItems,
  type StoredOpenItem,
} from "./openItems";
import { storedItem } from "@/test/openItemsFixtures";

afterEach(() => {
  fetchMock.mockReset();
});

function index(texts: string[]) {
  return buildItemLabelIndex(
    texts.map((text, position) => {
      const source: ItemLabelSource = { messageId: `m${position}`, role: "assistant", text };
      return { source, labels: itemLabelsIn(text), struck: struckItemLabelsIn(text) };
    }),
  );
}

const ITEMS = "- [Q1] **Backfill window.** Batch it?\n- [Q2] **Soft-deleted rows.** Copy or drop?";

describe("mergeStoredOpenItems", () => {
  it("returns the chat's index itself while the store holds nothing", () => {
    const chat = index([ITEMS]);
    expect(mergeStoredOpenItems(chat, null)).toBe(chat);
    expect(mergeStoredOpenItems(chat, [])).toBe(chat);
  });

  it("takes a stored label's state from the store, whatever the chat wrote", () => {
    const chat = index([ITEMS, "~~[Q1]~~ batching it."]);
    const merged = mergeStoredOpenItems(chat, [
      storedItem("Q1"),
      storedItem("Q2", { status: "closed", resolution: "Dropped them", closed_at: 1_764_100_500 }),
    ]);
    const q1 = merged.items.get("Q1")!;
    const q2 = merged.items.get("Q2")!;
    // The chat struck Q1 but the store keeps it open: open, with the chat's close offered.
    expect(q1.closedBy).toBeNull();
    expect(storedItemOf(q1)?.status).toBe("open");
    expect((q1 as { closedInChat?: ItemLabelSource }).closedInChat?.messageId).toBe("m1");
    // Closed only in the store: closed, described by its resolution at its latest mention.
    expect(q2.closedBy).toMatchObject({
      messageId: "m0",
      text: "~~[Q2]~~ Dropped them",
      createdAtS: 1_764_100_500,
    });
    // The parsed entry's own fields are kept.
    expect(q2.source).toBe(chat.items.get("Q2")!.source);
  });

  it("turns chips on for a stored label the chat mentions only once", () => {
    const chat = index(["[Q1] **Only once.**"]);
    expect(chat.enabled).toBe(false);
    expect(mergeStoredOpenItems(chat, [storedItem("Q1")]).enabled).toBe(true);
    expect(mergeStoredOpenItems(chat, [storedItem("Q9")]).enabled).toBe(false);
  });
});

describe("openItemRows", () => {
  it("lists stored items, then chat-only labels, in label order, without pinned links", () => {
    const chat = index([ITEMS, "- [R1] **Flaky.**\n- [A4] **Other letter.**", "[L1] pinned"]);
    const merged = mergeStoredOpenItems(chat, [
      storedItem("Q2", { status: "answered", topic: "cache" }),
      storedItem("T3"),
      storedItem("L1", { url: "https://example.com" }),
    ]);
    expect(openItemRows(chat, [], new Set()).map((row) => row.label)).toEqual([
      "Q1",
      "Q2",
      "R1",
      "A4",
    ]);

    const stored = [
      storedItem("Q2", { status: "answered", topic: "cache" }),
      storedItem("T3"),
      storedItem("L1", { url: "https://example.com" }),
    ];
    const all = openItemRows(merged, stored, new Set(["Q1"]));
    expect(all.map((row) => [row.label, row.status, row.stored !== null, row.dismissed])).toEqual([
      ["Q1", "open", false, true],
      ["Q2", "answered", true, false],
      ["R1", "open", false, false],
      ["T3", "open", true, false],
      ["A4", "open", false, false],
    ]);
    expect(all.find((row) => row.label === "Q1")?.title).toBe("Backfill window.");
    expect(all.find((row) => row.label === "A4")?.kind).toBeNull();
    // Answered items wait on the agent, and dismissed ones are out of the count.
    expect(countOpenRows(all)).toBe(3);
  });

  it("lists every stored item even when no loaded message mentions it", () => {
    const rows = openItemRows(null, [storedItem("Q4"), storedItem("F1")], new Set());
    expect(rows.map((row) => [row.label, row.entry])).toEqual([
      ["Q4", null],
      ["F1", null],
    ]);
  });

  it("offers the chat's closing sentence as the resolution", () => {
    const chat = index([ITEMS, "~~[Q1]~~ We batch it nightly. More later."]);
    const merged = mergeStoredOpenItems(chat, [storedItem("Q1")]);
    const [row] = openItemRows(merged, [storedItem("Q1")], new Set());
    expect(chatResolution(row)).toBe("[Q1] We batch it nightly.");
  });
});

describe("compareItemLabels", () => {
  it("orders by kind, then number, with other letters last", () => {
    const labels = ["A4", "T2", "Q10", "R1", "Q2", "AB1"];
    expect(labels.sort(compareItemLabels)).toEqual(["Q2", "Q10", "R1", "T2", "A4", "AB1"]);
  });
});

describe("withWrittenItems", () => {
  it("puts written items in place and keeps label order", () => {
    const cached = [storedItem("Q1"), storedItem("R1")];
    const written = withWrittenItems(cached, [
      { label: "R1", item: storedItem("R1", { status: "closed" }) },
      { label: "Q2", item: storedItem("Q2") },
      { label: "T9", error: { code: "not_found", message: "no item T9" } },
    ]);
    expect(written?.map((item) => [item.label, item.status])).toEqual([
      ["Q1", "open"],
      ["Q2", "open"],
      ["R1", "closed"],
    ]);
    expect(withWrittenItems(undefined, [])).toBeUndefined();
  });
});

describe("fetchStoredOpenItems", () => {
  it("reads every page of every status", async () => {
    const page = (data: StoredOpenItem[], nextAfter: string | null) =>
      new Response(JSON.stringify({ data, has_more: nextAfter !== null, next_after: nextAfter }));
    fetchMock
      .mockResolvedValueOnce(page([storedItem("Q1")], "Q1"))
      .mockResolvedValueOnce(page([storedItem("R1")], null));
    const items = await fetchStoredOpenItems("conv 1");
    expect(items.map((item) => item.label)).toEqual(["Q1", "R1"]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/v1/sessions/conv%201/open-items?status=all&limit=200",
      "/v1/sessions/conv%201/open-items?status=all&limit=200&after=Q1",
    ]);
  });

  it("fails with the server's reason", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { message: "Open items are not available" } }), {
        status: 404,
      }),
    );
    await expect(fetchStoredOpenItems("conv_1")).rejects.toThrow("Open items are not available");
  });
});
