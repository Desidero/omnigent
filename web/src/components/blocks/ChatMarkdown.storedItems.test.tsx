// A stored item's chip previews its thread from the store, each reply once,
// never sentences found in the chat; a label only in the chat offers Record.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildItemCommentMessage, scanItemLabelSource } from "@/lib/itemComments";
import {
  registerItemCommentComposer,
  resetItemCommentDraftsForTests,
} from "@/lib/itemCommentDrafts";
import {
  ItemLabelIndexContext,
  ItemLabelMessageContext,
  ItemLabelSessionContext,
  buildItemLabelIndex,
  type ItemLabelIndex,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import { mergeStoredOpenItems } from "@/lib/openItems";
import { storedItem } from "@/test/openItemsFixtures";
import { FilePathAwareMessageResponse } from "./ChatMarkdown";

const fetchMock = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => vi.fn());
vi.mock(import("@/lib/identity"), async (importOriginal) => ({
  ...(await importOriginal()),
  authenticatedFetch: fetchMock,
}));
vi.mock("@/components/ui/toast", () => ({ showToast: toastMock }));
vi.mock(import("@/lib/capabilities"), async (importOriginal) => ({
  ...(await importOriginal()),
  getCachedServerInfo: () => ({ open_items: true }) as never,
}));

const SESSION_ID = "conv_1";

afterEach(() => {
  cleanup();
  fetchMock.mockReset();
  toastMock.mockReset();
  resetItemCommentDraftsForTests();
});

const DEFINING: ItemLabelSource = {
  messageId: "resp_defining",
  role: "assistant",
  text: "- [Q1] **Cache per user?** It changes eviction.\n- [R1] **Flaky test.** It times out.",
};
const COMMENT: ItemLabelSource = {
  messageId: "msg_comment",
  role: "user",
  text: buildItemCommentMessage([
    { label: "Q1", title: "Cache per user?", comments: [{ text: "Why?", attachments: [] }] },
  ]),
};
// The agent's chat answer repeats the label and strikes it; neither shows in the card.
const ANSWER: ItemLabelSource = {
  messageId: "resp_answer",
  role: "assistant",
  text: "~~[Q1]~~ Yes, per user: eviction stays fair.",
};

function chatIndex(): ItemLabelIndex {
  return buildItemLabelIndex([DEFINING, COMMENT, ANSWER].map((s) => scanItemLabelSource(s)));
}

function renderChip(markdown: string, index: ItemLabelIndex) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/c/conv_1"]}>
        <ItemLabelSessionContext.Provider value={SESSION_ID}>
          <ItemLabelIndexContext.Provider value={index}>
            <ItemLabelMessageContext.Provider value="resp_later">
              <FilePathAwareMessageResponse>{markdown}</FilePathAwareMessageResponse>
            </ItemLabelMessageContext.Provider>
          </ItemLabelIndexContext.Provider>
        </ItemLabelSessionContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("a stored item's chip", () => {
  it("shows the stored thread and resolution once, not the chat's reply or close", async () => {
    const index = mergeStoredOpenItems(chatIndex(), [
      storedItem("Q1", {
        status: "closed",
        closed_by: "agent",
        closed_at: 1_764_100_300,
        resolution: "Per user",
        replies: [
          { author: "user", text: "Why?", at: 1_764_100_100 },
          { author: "agent", text: "Eviction stays fair per user.", at: 1_764_100_200 },
        ],
      }),
    ]);
    renderChip("Recap: [Q1].", index);
    const chip = await screen.findByRole("button", { name: /Show item Q1/ });
    expect(chip.className).toContain("line-through");
    fireEvent.click(chip);

    const replies = await screen.findAllByTestId("open-item-reply");
    expect(replies.map((reply) => reply.dataset.author)).toEqual(["user", "agent"]);
    expect(screen.queryByText(/Agent replied/)).toBeNull();
    expect(screen.queryByText(/Yes, per user/)).toBeNull();
    expect(screen.queryByTestId("item-comment")).toBeNull();
    const resolution = screen.getByTestId("open-item-resolution");
    expect(resolution.textContent).toContain("Closed by the agent");
    expect(resolution.textContent).toContain("Per user");
    expect(screen.queryByRole("button", { name: "Record" })).toBeNull();
  });

  it("stays open when the chat struck its label but the store keeps it open", async () => {
    const index = mergeStoredOpenItems(chatIndex(), [storedItem("Q1"), storedItem("R1")]);
    renderChip("Recap: [Q1].", index);
    const chip = await screen.findByRole("button", { name: /Show item Q1/ });
    expect(chip.className).not.toContain("line-through");
  });
});

describe("a label only in the chat", () => {
  it("offers Record to a person who can comment, and stores it under its own label", async () => {
    const unregister = registerItemCommentComposer(SESSION_ID);
    const index = mergeStoredOpenItems(chatIndex(), [storedItem("Q1")]);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [{ item: storedItem("R1") }] })),
    );
    renderChip("Still flaky: [R1].", index);
    fireEvent.click(await screen.findByRole("button", { name: /Show item R1/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Record" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/sessions/conv_1/open-items/import");
    expect(JSON.parse(init.body as string).items).toEqual([
      expect.objectContaining({ kind: "risk", label: "R1", title: "Flaky test." }),
    ]);
    await waitFor(() => expect(toastMock).toHaveBeenCalledWith("Recorded R1 as an open item"));
    unregister();
  });
});
