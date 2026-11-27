import { afterEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => vi.fn());
const serverInfo = vi.hoisted(() => ({ current: { open_items: true } as object | null }));
const toastMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch: fetchMock }));
vi.mock("@/components/ui/toast", () => ({ showToast: toastMock }));
vi.mock(import("@/lib/capabilities"), async (importOriginal) => ({
  ...(await importOriginal()),
  getCachedServerInfo: () => serverInfo.current as never,
}));

import { act, renderHook } from "@testing-library/react";
import {
  getItemCommentState,
  resetItemCommentDraftsForTests,
  saveItemCommentDraft,
} from "@/lib/itemCommentDrafts";
import { buildItemCommentMessage, parseItemCommentMessage } from "@/lib/itemComments";
import { storedItem } from "@/test/openItemsFixtures";
import {
  answersInCommentMessage,
  closableItemLabels,
  itemCommentHeadingTitle,
  publishStoredOpenItems,
  commentMessageRef,
  recordItemCommentAnswers,
  recordItemCommentsBeforeSend,
  resetClosableItemLabelsForTests,
  setItemCommentsClose,
  useItemCommentClosingLabels,
} from "./openItemAnswers";

afterEach(() => {
  fetchMock.mockReset();
  toastMock.mockReset();
  serverInfo.current = { open_items: true };
  vi.restoreAllMocks();
  resetItemCommentDraftsForTests();
  resetClosableItemLabelsForTests();
  localStorage.clear();
});

const ok = (body: object) => new Response(JSON.stringify(body));
const sentBodies = () =>
  fetchMock.mock.calls.map((call) => {
    const [url, init] = call as [string, RequestInit];
    return [url, init.method, JSON.parse(init.body as string)];
  });

const MESSAGE = buildItemCommentMessage(
  [
    {
      label: "Q2",
      title: "Soft-deleted rows",
      comments: [
        { text: "Drop them.", attachments: [] },
        { text: "", attachments: ["rows.png"] },
      ],
    },
    { label: "A4", title: "Other letter", comments: [{ text: "Fine.", attachments: [] }] },
    { label: "R1", title: "Flaky", comments: [{ text: "x".repeat(2100), attachments: [] }] },
  ],
  { text: "Thanks!", attachments: [] },
);

describe("answersInCommentMessage", () => {
  it("gives one answer per stored-kind item, its comments joined", () => {
    expect(answersInCommentMessage(MESSAGE)).toEqual([
      { label: "Q2", text: "Drop them.\n\nAttachments: rows.png" },
      { label: "R1", text: "x".repeat(2000) },
    ]);
    expect(answersInCommentMessage("Just a message about [Q2].")).toEqual([]);
  });
});

describe("recordItemCommentAnswers", () => {
  it("posts the replies, named after the message, where the server stores open items", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ items: [] })));
    await recordItemCommentAnswers("conv 1", MESSAGE);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/sessions/conv%201/open-items/replies");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.replies.map((a: { label: string }) => a.label)).toEqual(["Q2", "R1"]);
    // The same message sent again carries the same ref, so the server adds nothing.
    expect(body.ref).toMatch(/^comment:[0-9a-f]{32}$/);
    expect(body.ref).toBe(await commentMessageRef(MESSAGE));
    expect(await commentMessageRef(`${MESSAGE} `)).not.toBe(body.ref);
  });

  it("does nothing on a server without open items", async () => {
    serverInfo.current = { open_items: false };
    await recordItemCommentAnswers("conv_1", MESSAGE);
    serverInfo.current = null;
    await recordItemCommentAnswers("conv_1", MESSAGE);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never throws: a refused or failed call only leaves the items open", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 403 }));
    await expect(recordItemCommentAnswers("conv_1", MESSAGE)).resolves.toBeUndefined();
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(recordItemCommentAnswers("conv_1", MESSAGE)).resolves.toBeUndefined();
    expect(warn).toHaveBeenCalledTimes(2);
  });
});

describe("recordItemCommentsBeforeSend", () => {
  it("lets the message go when the server is slow", async () => {
    vi.useFakeTimers();
    try {
      fetchMock.mockReturnValueOnce(new Promise(() => {}));
      const waited = recordItemCommentsBeforeSend("conv_1", MESSAGE);
      await vi.advanceTimersByTimeAsync(3000);
      await expect(waited).resolves.toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Comment and close", () => {
  const CLOSING = buildItemCommentMessage([
    {
      label: "Q2",
      title: itemCommentHeadingTitle("Soft-deleted rows", true),
      comments: [{ text: "Drop them.", attachments: [] }],
    },
    {
      label: "R1",
      title: itemCommentHeadingTitle("Flaky", false),
      comments: [{ text: "Retry once.", attachments: [] }],
    },
  ]);

  it("marks the heading of an item the comments close, and reads back as before", () => {
    expect(CLOSING).toContain("#### [Q2] Soft-deleted rows (closed by me)\n\nDrop them.");
    expect(CLOSING).toContain("#### [R1] Flaky\n\nRetry once.");
    expect(parseItemCommentMessage(CLOSING)?.sections.map((s) => [s.label, s.title])).toEqual([
      ["Q2", "Soft-deleted rows (closed by me)"],
      ["R1", "Flaky"],
    ]);
    expect(answersInCommentMessage(CLOSING)).toEqual([
      { label: "Q2", text: "Drop them." },
      { label: "R1", text: "Retry once." },
    ]);
  });

  it("records every reply, then closes the chosen items as the user with their comments", async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [] }));
    fetchMock.mockResolvedValueOnce(ok({ items: [{ label: "Q2", item: storedItem("Q2") }] }));
    await recordItemCommentAnswers("conv_1", CLOSING, ["Q2"]);
    expect(sentBodies()).toEqual([
      [
        "/v1/sessions/conv_1/open-items/replies",
        "POST",
        {
          replies: [
            { label: "Q2", text: "Drop them." },
            { label: "R1", text: "Retry once." },
          ],
          ref: await commentMessageRef(CLOSING),
        },
      ],
      [
        "/v1/sessions/conv_1/open-items",
        "PATCH",
        { updates: [{ label: "Q2", status: "closed", resolution: "Drop them." }] },
      ],
    ]);
    expect(toastMock).not.toHaveBeenCalled();
  });

  it("cuts the resolution to the store's limit", async () => {
    fetchMock.mockResolvedValue(ok({ items: [] }));
    await recordItemCommentAnswers("conv_1", MESSAGE, ["R1"]);
    const [, , patch] = sentBodies()[1];
    expect(patch.updates).toEqual([
      { label: "R1", status: "closed", resolution: "x".repeat(2000) },
    ]);
  });

  it("leaves an item it could not close open, with its answer, and says so", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    fetchMock.mockResolvedValueOnce(ok({ items: [] }));
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 500 }));
    await expect(recordItemCommentAnswers("conv_1", CLOSING, ["Q2"])).resolves.toBeUndefined();
    expect(sentBodies().map(([url]) => url)).toEqual([
      "/v1/sessions/conv_1/open-items/replies",
      "/v1/sessions/conv_1/open-items",
    ]);
    expect(toastMock).toHaveBeenCalledWith(
      "Your comments are on their items, but Q2 couldn't be closed; it stays open.",
    );
    expect(warn).toHaveBeenCalledTimes(1);

    fetchMock.mockResolvedValueOnce(ok({ items: [] }));
    fetchMock.mockResolvedValueOnce(
      ok({ items: [{ label: "Q2", error: { code: "not_found", message: "no item Q2" } }] }),
    );
    await recordItemCommentAnswers("conv_1", CLOSING, ["Q2"]);
    expect(toastMock).toHaveBeenCalledTimes(2);
  });

  it("never closes on a server without open items", async () => {
    serverInfo.current = { open_items: false };
    await recordItemCommentAnswers("conv_1", CLOSING, ["Q2"]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("offers closing only on stored items that are not closed", () => {
    expect(closableItemLabels("conv_1").size).toBe(0);
    publishStoredOpenItems("conv_1", [
      storedItem("Q1"),
      storedItem("Q2", { status: "answered" }),
      storedItem("Q3", { status: "closed" }),
    ]);
    expect([...closableItemLabels("conv_1")]).toEqual(["Q1", "Q2"]);
    expect(closableItemLabels("conv_2").size).toBe(0);
    publishStoredOpenItems("conv_1", null);
    expect(closableItemLabels("conv_1").size).toBe(0);
  });

  it("sets closing on every unsent draft of the item and lists the closing labels", () => {
    const draft = (id: string, label: string) => ({
      id,
      label,
      title: "",
      text: id,
      files: [],
      createdAt: 1,
    });
    saveItemCommentDraft("conv_1", draft("d1", "Q2"));
    saveItemCommentDraft("conv_1", draft("d2", "Q2"));
    saveItemCommentDraft("conv_1", draft("d3", "R1"));
    const { result } = renderHook(() => useItemCommentClosingLabels("conv_1"));
    act(() => setItemCommentsClose("conv_1", "Q2", true));
    expect(getItemCommentState("conv_1").drafts.map((d) => d.closes)).toEqual([
      true,
      true,
      undefined,
    ]);
    expect([...result.current]).toEqual(["Q2"]);
    act(() => setItemCommentsClose("conv_1", "Q2", false));
    expect(result.current.size).toBe(0);
  });
});
