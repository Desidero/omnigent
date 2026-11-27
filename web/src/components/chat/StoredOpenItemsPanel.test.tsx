import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const viewport = vi.hoisted(() => ({ mobile: false }));
const access = vi.hoisted(() => ({ canEdit: true }));
const fetchMock = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useIsMobileViewport", () => ({ useIsMobileViewport: () => viewport.mobile }));
vi.mock("@/hooks/usePermissions", () => ({ useCanEdit: () => access.canEdit }));
vi.mock(import("@/lib/identity"), async (importOriginal) => ({
  ...(await importOriginal()),
  authenticatedFetch: fetchMock,
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  registerItemCommentComposer,
  resetItemCommentDraftsForTests,
  saveItemCommentDraft,
  useItemCommentRequest,
} from "@/lib/itemCommentDrafts";
import { useStoredOpenItems } from "@/hooks/useStoredOpenItems";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import type { ServerInfo } from "@/lib/capabilities";
import {
  DISMISSED_ITEMS_LABEL_KEY,
  ItemLabelIndexContext,
  ItemLabelSessionContext,
  buildItemLabelIndex,
  itemLabelsIn,
  struckItemLabelsIn,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import { mergeStoredOpenItems, openItemsKey, type StoredOpenItem } from "@/lib/openItems";
import { collectSessionLinks } from "@/lib/sessionLinks";
import { SessionItemsHeaderSlot, useSessionItemsHeaderHost } from "@/shell/SessionItemsHeaderSlot";
import { storedItem } from "@/test/openItemsFixtures";
import { SessionItemsButton } from "./SessionItemsButton";
import { PANEL_CLOSE_RESOLUTION } from "./StoredOpenItemsPanel";

beforeEach(() => {
  viewport.mobile = false;
  access.canEdit = true;
});

afterEach(() => {
  cleanup();
  fetchMock.mockReset();
});

/** The header button inside the label scope the transcript gives it, store merged in. */
function TranscriptItems({ sources }: { sources: ItemLabelSource[] }) {
  const host = useSessionItemsHeaderHost("conv_1");
  const index = buildItemLabelIndex(
    sources.map((source) => ({
      source,
      labels: itemLabelsIn(source.text),
      struck: struckItemLabelsIn(source.text),
    })),
  );
  const merged = mergeStoredOpenItems(index, useStoredOpenItems("conv_1"));
  return (
    <ItemLabelIndexContext.Provider value={merged}>
      <ItemLabelSessionContext.Provider value="conv_1">
        {host && <SessionItemsButton host={host} links={collectSessionLinks(sources, index)} />}
      </ItemLabelSessionContext.Provider>
    </ItemLabelIndexContext.Provider>
  );
}

function renderPanel(
  texts: string[],
  stored: StoredOpenItem[] | null,
  labels: Record<string, string> = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(["session", "conv_1"], { id: "conv_1", labels });
  if (stored) queryClient.setQueryData(openItemsKey("conv_1"), stored);
  const info = (stored ? { open_items: true } : { open_items: false }) as ServerInfo;
  const sources = texts.map((text, position): ItemLabelSource => ({
    messageId: `m${position}`,
    role: "assistant",
    text,
  }));
  render(
    <QueryClientProvider client={queryClient}>
      <CapabilitiesProvider info={info}>
        <MemoryRouter>
          <TooltipProvider>
            <SessionItemsHeaderSlot sessionId="conv_1" />
            <TranscriptItems sources={sources} />
          </TooltipProvider>
        </MemoryRouter>
      </CapabilitiesProvider>
    </QueryClientProvider>,
  );
  return queryClient;
}

const ITEMS = "- [Q1] **Backfill window.** Batch it?\n- [Q2] **Soft-deleted rows.** Copy or drop?";
const badge = () => screen.queryByTestId("session-items-count")?.textContent ?? null;
const openPanel = () => {
  fireEvent.click(screen.getByTestId("session-items-trigger"));
  return within(screen.getByTestId("session-items-panel")).getByTestId("open-items");
};
const rowLabels = (panel: HTMLElement) =>
  within(panel)
    .queryAllByTestId("open-item-row")
    .map((row) => row.getAttribute("data-label"));

function respondWith(items: StoredOpenItem[]) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify({ items: items.map((item) => ({ label: item.label, item })) })),
  );
}

async function patchBody(call = 0) {
  await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(call));
  const [url, init] = fetchMock.mock.calls[call] as [string, RequestInit];
  expect(url).toBe("/v1/sessions/conv_1/open-items");
  expect(init.method).toBe("PATCH");
  return JSON.parse(init.body as string);
}

describe("the Open items panel on a server that stores them", () => {
  it("counts stored items by their stored status and lists chat-only labels as such", () => {
    renderPanel(
      [ITEMS, "- [R1] **Flaky test.**\n- [T1] **Rename later.**", "~~[Q1]~~ batching it."],
      [
        storedItem("Q1", { title: "Backfill window" }),
        storedItem("Q2", { status: "answered" }),
        storedItem("F3", { title: "Raised before the loaded history" }),
      ],
    );
    // Q1 stays open (the store says so), F3 counts though no loaded message has it,
    // R1 and T1 are chat-only and open; Q2 waits on the agent.
    expect(badge()).toBe("4");
    const panel = openPanel();
    expect(rowLabels(panel)).toEqual(["Q1", "R1", "F3", "T1", "Q2"]);
    expect(panel.textContent).toContain("Answered (1)");
    const r1 = within(panel).getByRole("button", { name: "Item R1, chat only" });
    expect(r1.textContent).toContain("chat only");
    // The chat struck Q1, but chat text never changes a stored item.
    const q1 = within(panel).getByRole("button", { name: "Item Q1" });
    expect(q1.textContent).not.toContain("closed in chat");
    expect(within(panel).getByRole("button", { name: "Dismiss item R1" })).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Close item Q1" })).toBeTruthy();
  });

  it("shows the button for stored items when no loaded message has a label", () => {
    renderPanel(["Nothing labelled here."], [storedItem("Q7")]);
    expect(badge()).toBe("1");
    expect(rowLabels(openPanel())).toEqual(["Q7"]);
  });

  it("closes a stored item in one tap through the API instead of dismissing it", async () => {
    const queryClient = renderPanel(
      [ITEMS, "Still on [Q2]."],
      [storedItem("Q1"), storedItem("Q2")],
    );
    expect(badge()).toBe("2");
    const panel = openPanel();
    respondWith([
      storedItem("Q2", { status: "closed", resolution: PANEL_CLOSE_RESOLUTION, closed_by: "user" }),
    ]);
    fireEvent.click(within(panel).getByRole("button", { name: "Close item Q2" }));
    expect(await patchBody()).toEqual({
      updates: [{ label: "Q2", status: "closed", resolution: PANEL_CLOSE_RESOLUTION }],
    });
    await waitFor(() => expect(badge()).toBe("1"));
    // The latest reply mentions Q2, so it stays first, struck through.
    expect(within(panel).getByRole("button", { name: "Item Q2 (closed)" })).toBeTruthy();
    // No dismissed-items label is written for a stored item.
    const session = queryClient.getQueryData<{ labels: Record<string, string> }>([
      "session",
      "conv_1",
    ]);
    expect(session?.labels[DISMISSED_ITEMS_LABEL_KEY]).toBeUndefined();
  });

  it("expands a row to its detail, thread and outcome, and reopens or retopics it", async () => {
    renderPanel(
      [ITEMS, "~~[Q1]~~ done.", "Looking at the rest."],
      [
        storedItem("Q1", {
          status: "closed",
          detail: "Batch the **backfill** nightly?",
          resolution: "Nightly batches",
          closed_by: "agent",
          closed_at: 1_764_100_500,
          replies: [
            { author: "user", text: "Nightly?", at: 1_764_100_100, by: "bob@example.com" },
            { author: "agent", text: "Yes, nightly", at: 1_764_100_200 },
          ],
          links: [{ url: "https://example.com/pr/1", label: "PR 1" }],
          topic: "cache",
        }),
      ],
    );
    // Q2 is a chat-only open item.
    expect(badge()).toBe("1");
    const panel = openPanel();
    fireEvent.click(within(panel).getByRole("button", { name: "Closed (1)" }));
    fireEvent.click(within(panel).getByRole("button", { name: "Item Q1 (closed)" }));
    const details = within(panel).getByTestId("open-item-details");
    expect(details.textContent).toContain("backfill");
    expect(
      within(details)
        .getAllByTestId("open-item-reply")
        .map((reply) => [reply.dataset.author, reply.textContent]),
    ).toEqual([
      ["user", expect.stringContaining("Nightly?")],
      ["agent", expect.stringContaining("Yes, nightly")],
    ]);
    expect(details.textContent).toContain("bob@example.com");
    expect(details.textContent).toContain("Closed by the agent");
    expect(details.textContent).toContain("Nightly batches");
    expect(within(details).getByRole("link", { name: "PR 1" })).toBeTruthy();

    respondWith([storedItem("Q1", { topic: "cache" })]);
    fireEvent.click(within(details).getByRole("button", { name: "Reopen" }));
    expect(await patchBody()).toEqual({ updates: [{ label: "Q1", status: "open" }] });
    await waitFor(() => expect(badge()).toBe("2"));

    respondWith([storedItem("Q1", { topic: "release" })]);
    const topic = within(panel).getByRole("combobox", { name: "Topic of Q1" });
    fireEvent.change(topic, { target: { value: "release" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Set topic" }));
    expect(await patchBody(1)).toEqual({ updates: [{ label: "Q1", topic: "release" }] });
  });

  it("shows each reply once and leaves out a resolution that repeats the last one", () => {
    renderPanel(
      [ITEMS, "Looking at the rest."],
      [
        storedItem("Q1", {
          status: "closed",
          closed_by: "user",
          resolution: "Copy them as they are.",
          closed_at: 1_764_100_500,
          replies: [{ author: "user", text: "Copy them as they are.", at: 1_764_100_400 }],
        }),
      ],
    );
    const panel = openPanel();
    fireEvent.click(within(panel).getByRole("button", { name: "Closed (1)" }));
    fireEvent.click(within(panel).getByRole("button", { name: "Item Q1 (closed)" }));
    const details = within(panel).getByTestId("open-item-details");
    expect(details.textContent?.split("Copy them as they are.").length).toBe(2);
    expect(within(details).getByTestId("open-item-resolution").textContent).toContain(
      "Closed by a person",
    );
  });

  it("imports the chat's own labels into the store", async () => {
    renderPanel([ITEMS, "- [R1] **Flaky.**", "~~[R1]~~ fixed."], [storedItem("Q2")]);
    const panel = openPanel();
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [
            { item: storedItem("Q1", { title: "Backfill window." }) },
            { item: storedItem("R1", { status: "closed", title: "Flaky." }) },
          ],
        }),
      ),
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Import 2 from chat" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/sessions/conv_1/open-items/import");
    expect(
      JSON.parse(init.body as string).items.map((item: { label: string }) => item.label),
    ).toEqual(["Q1", "R1"]);
    await waitFor(() =>
      expect(within(panel).queryByRole("button", { name: /from chat$/ })).toBeNull(),
    );
    expect(within(panel).queryByText("chat only")).toBeNull();
  });

  it("starts a comment on a stored item from its details, closing the panel", () => {
    const unregister = registerItemCommentComposer("conv_1");
    let request: ReturnType<typeof useItemCommentRequest> = null;
    function RequestProbe() {
      request = useItemCommentRequest("conv_1");
      return null;
    }
    render(<RequestProbe />);
    renderPanel(["Nothing labelled."], [storedItem("Q7", { title: "Cache rows?" })]);
    const panel = openPanel();
    fireEvent.click(within(panel).getByRole("button", { name: "Item Q7" }));
    fireEvent.click(within(panel).getByRole("button", { name: "Comment" }));
    expect(request).toMatchObject({ label: "Q7", title: "Cache rows?" });
    expect(request).not.toHaveProperty("closes");
    expect(screen.queryByTestId("session-items-panel")).toBeNull();
    unregister();
    resetItemCommentDraftsForTests();
  });

  it("offers Comment and close on a stored item that is not closed, and marks closing rows", () => {
    const unregister = registerItemCommentComposer("conv_1");
    let request: ReturnType<typeof useItemCommentRequest> = null;
    function RequestProbe() {
      request = useItemCommentRequest("conv_1");
      return null;
    }
    render(<RequestProbe />);
    saveItemCommentDraft("conv_1", {
      id: "d1",
      label: "Q8",
      title: "",
      text: "Done.",
      files: [],
      createdAt: 1,
      closes: true,
    });
    renderPanel(
      ["Nothing labelled."],
      [
        storedItem("Q7", { title: "Cache rows?" }),
        storedItem("Q8"),
        storedItem("Q9", { status: "closed", resolution: "Done" }),
      ],
    );
    const panel = openPanel();
    const row = (label: string) =>
      within(panel)
        .getAllByTestId("open-item-row")
        .find((element) => element.dataset.label === label)!;
    expect(within(row("Q8")).getByText("closes when sent")).toBeTruthy();
    expect(within(row("Q7")).queryByText("closes when sent")).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Item Q7" }));
    fireEvent.click(within(panel).getByRole("button", { name: "Comment and close" }));
    expect(request).toMatchObject({ label: "Q7", title: "Cache rows?", closes: true });
    unregister();
    resetItemCommentDraftsForTests();
  });

  it("offers no changes to a viewer without edit access", () => {
    access.canEdit = false;
    renderPanel([ITEMS, "More on [Q2]."], [storedItem("Q1"), storedItem("Q2")]);
    const panel = openPanel();
    expect(within(panel).queryByRole("button", { name: /^Close item/ })).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Item Q2" }));
    expect(within(panel).queryByRole("button", { name: "Close" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Set topic" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /from chat$/ })).toBeNull();
  });

  it("keeps the chat's tracker, unchanged, where the server stores no items", () => {
    renderPanel([ITEMS, "More on [Q2]."], null);
    const panel = openPanel();
    expect(panel.tagName).toBe("DETAILS");
    expect(within(panel).getByRole("button", { name: "Dismiss item Q1" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
