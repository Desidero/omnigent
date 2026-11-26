import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@/hooks/useIsMobileViewport", () => ({ useIsMobileViewport: () => viewport.mobile }));

import type { Session } from "@/lib/types";
import {
  DISMISSED_ITEMS_LABEL_KEY,
  ItemLabelIndexContext,
  ItemLabelSessionContext,
  buildItemLabelIndex,
  itemLabelsIn,
  struckItemLabelsIn,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import { requestItemComment } from "@/lib/itemCommentDrafts";
import { collectSessionLinks } from "@/lib/sessionLinks";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SessionItemsHeaderSlot, useSessionItemsHeaderHost } from "@/shell/SessionItemsHeaderSlot";
import { SessionItemsButton } from "./SessionItemsButton";

beforeEach(() => {
  viewport.mobile = false;
});

afterEach(() => {
  cleanup();
});

/** The button as the transcript mounts it: in the header slot, or nothing without one. */
function TranscriptItems({ sources }: { sources: ItemLabelSource[] }) {
  const host = useSessionItemsHeaderHost("conv_1");
  const index = buildItemLabelIndex(
    sources.map((source) => ({
      source,
      labels: itemLabelsIn(source.text),
      struck: struckItemLabelsIn(source.text),
    })),
  );
  return (
    <ItemLabelIndexContext.Provider value={index}>
      <ItemLabelSessionContext.Provider value="conv_1">
        {host ? (
          <SessionItemsButton host={host} links={collectSessionLinks(sources, index)} />
        ) : (
          <span data-testid="no-header-slot" />
        )}
      </ItemLabelSessionContext.Provider>
    </ItemLabelIndexContext.Provider>
  );
}

function renderButton(texts: string[], labels: Session["labels"] = {}, header = true) {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["session", "conv_1"], { id: "conv_1", labels });
  const sources = texts.map((text, position): ItemLabelSource => ({
    messageId: `m${position}`,
    role: "assistant",
    text,
  }));
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TooltipProvider>
          <header data-testid="header">
            {header && <SessionItemsHeaderSlot sessionId="conv_1" />}
          </header>
          <main data-testid="transcript">
            <TranscriptItems sources={sources} />
          </main>
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ITEMS = "- [Q1] **Backfill window.** Batch it?\n- [Q2] **Soft-deleted rows.** Copy or drop?";
const PIN = "[L1] **Release checklist** https://example.com/checklist";
const PUBLISHED = "Published the [Patch catalog](https://claude.ai/artifact/aaa).";

const trigger = () => screen.getByTestId("session-items-trigger");
const openPanel = () => {
  fireEvent.click(trigger());
  return screen.getByTestId("session-items-panel");
};

describe("SessionItemsButton", () => {
  it("renders in the header slot with the open count as its badge", () => {
    renderButton([ITEMS, "~~[Q1]~~ batching it.", PIN]);

    expect(within(screen.getByTestId("header")).getByTestId("session-items-trigger")).toBe(
      trigger(),
    );
    expect(screen.getByTestId("transcript").contains(trigger())).toBe(false);
    // Q2 is open; Q1 is closed and L1 is a link, not an item.
    expect(screen.getByTestId("session-items-count").textContent).toBe("1");
    expect(trigger().getAttribute("aria-label")).toBe("Open items and links (1 open)");
    expect(screen.queryByTestId("session-items-panel")).toBeNull();
  });

  it("leaves dismissed items out of the badge", () => {
    renderButton([ITEMS, "Looking."], { [DISMISSED_ITEMS_LABEL_KEY]: "Q2" });
    expect(screen.getByTestId("session-items-count").textContent).toBe("1");
  });

  it("shows no badge when only links are listed, and no button with neither", () => {
    renderButton([PUBLISHED]);
    expect(trigger().getAttribute("aria-label")).toBe("Open items and links");
    expect(screen.queryByTestId("session-items-count")).toBeNull();
    cleanup();

    renderButton(["Use [A4] paper.", "See https://example.com/unrelated."]);
    expect(screen.queryByTestId("session-items-trigger")).toBeNull();
  });

  it("is not rendered without a header slot", () => {
    renderButton([ITEMS, PIN], {}, false);
    expect(screen.getByTestId("no-header-slot")).toBeTruthy();
    expect(screen.queryByTestId("session-items-trigger")).toBeNull();
  });

  it("opens a panel with the open items tracker, expanded, and the links", () => {
    renderButton([ITEMS, "~~[Q1]~~ batching it.", PUBLISHED, PIN]);
    const panel = openPanel();

    const items = within(panel).getByTestId("open-items") as HTMLDetailsElement;
    expect(items.open).toBe(true);
    expect(items.textContent).toContain("Open items(1)");
    expect(items.textContent).toContain("Closed (1)");
    expect(within(items).getAllByRole("button", { name: "Show item Q2" })).toHaveLength(2);
    expect(within(items).getByRole("button", { name: "Dismiss item Q2" })).toBeTruthy();
    expect(items.textContent).not.toContain("L1");
    // Unlike the pinned bar, a press elsewhere in the panel leaves the list expanded.
    fireEvent.pointerDown(document.body);
    expect(items.open).toBe(true);

    const links = within(panel).getByTestId("session-links");
    expect(links.textContent).toContain("Links(2)");
    const [pinned, published] = within(links).getAllByRole("link") as HTMLAnchorElement[];
    expect(pinned.textContent).toContain("Release checklist");
    expect(pinned.textContent).toContain("example.com");
    expect(pinned.href).toBe("https://example.com/checklist");
    expect(published.textContent).toContain("Patch catalog");
    expect(published.href).toBe("https://claude.ai/artifact/aaa");
    for (const link of [pinned, published]) {
      expect(link.target).toBe("_blank");
      expect(link.rel).toBe("noopener noreferrer");
    }
    expect(within(links).getByRole("button", { name: "Show link L1" })).toBeTruthy();
  });

  it("says what Links collects while there are none, and omits the tracker without items", () => {
    renderButton([ITEMS, "Looking."]);
    expect(within(openPanel()).getByTestId("session-links").textContent).toContain("[L1]");
    cleanup();

    renderButton([PUBLISHED]);
    const panel = openPanel();
    expect(within(panel).queryByTestId("open-items")).toBeNull();
    expect(within(panel).getAllByRole("link")).toHaveLength(1);
  });

  it("closes when an item's preview jumps to its message", () => {
    renderButton([ITEMS, "Still need [Q2]."]);
    const panel = openPanel();
    fireEvent.click(within(panel).getAllByRole("button", { name: /^Show item Q2/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Show in conversation" }));
    expect(screen.queryByTestId("session-items-panel")).toBeNull();
  });

  it("closes when a comment on an item is started, on desktop and on a phone", () => {
    for (const mobile of [false, true]) {
      viewport.mobile = mobile;
      renderButton([ITEMS, "Still need [Q2]."]);
      openPanel();
      act(() => requestItemComment("conv_1", { label: "Q2", title: "Soft-deleted rows." }));
      expect(screen.queryByTestId("session-items-panel")).toBeNull();
      cleanup();
    }
  });

  it("opens as a dialog on a phone, with the same sections", () => {
    viewport.mobile = true;
    renderButton([ITEMS, "Looking.", PUBLISHED]);
    expect(screen.getByTestId("session-items-count").textContent).toBe("2");

    const panel = openPanel();
    expect(panel.getAttribute("role")).toBe("dialog");
    expect(within(panel).getByText("Open items and links")).toBeTruthy();
    expect((within(panel).getByTestId("open-items") as HTMLDetailsElement).open).toBe(true);
    expect(within(panel).getByRole("link").textContent).toContain("Patch catalog");
  });
});
