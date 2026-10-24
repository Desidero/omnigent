import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/sessionsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof SessionsApiModule>()),
  updateSession: vi.fn(),
}));

import type * as SessionsApiModule from "@/lib/sessionsApi";
import { updateSession } from "@/lib/sessionsApi";
import type { Session } from "@/lib/types";
import {
  DISMISSED_ITEMS_LABEL_KEY,
  ItemLabelIndexContext,
  ItemLabelSessionContext,
  buildItemLabelIndex,
  itemLabelsIn,
  struckItemLabelsIn,
  type ItemLabelIndex,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import { OpenItemsPanel, fitItemChipCount } from "./OpenItemsPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function indexOf(...texts: string[]): ItemLabelIndex {
  return buildItemLabelIndex(
    texts.map((text, position) => {
      const source: ItemLabelSource = { messageId: `m${position}`, role: "assistant", text };
      return { source, labels: itemLabelsIn(text), struck: struckItemLabelsIn(text) };
    }),
  );
}

function renderPanel(index: ItemLabelIndex, session?: Pick<Session, "id" | "labels">) {
  const queryClient = new QueryClient();
  if (session) queryClient.setQueryData(["session", session.id], session);
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ItemLabelIndexContext.Provider value={index}>
          <ItemLabelSessionContext.Provider value={session?.id ?? null}>
            <OpenItemsPanel />
          </ItemLabelSessionContext.Provider>
        </ItemLabelIndexContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OpenItemsPanel", () => {
  it("lists open items in the header and every item with its title below", () => {
    renderPanel(
      indexOf(
        "- **[Q1] Backfill window.** Batch it?\n- **[Q2] Soft-deleted rows.** Copy or drop?",
        "~~[Q1]~~ batching it.",
        "Tests pass.",
      ),
    );

    const panel = screen.getByTestId("open-items");
    expect(panel.textContent).toContain("Open items(1)");
    expect(screen.getAllByRole("button", { name: "Show item Q2" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Show item Q1 (closed)" }).textContent).toContain(
      "Backfill window.",
    );
    expect(panel.textContent).toContain("Closed (1)");
    expect(panel.textContent).not.toContain("In the latest reply");
  });

  it("puts the items the latest reply mentions first, tinted, including one it just closed", () => {
    renderPanel(
      indexOf(
        ["Q1", "Q2", "Q3", "Q4"].map((label) => `- **[${label}] Item ${label}.**`).join("\n"),
        "~~[Q1]~~ batched.",
        "~~[Q2]~~ dropped. [Q3] is next.",
      ),
    );

    const panel = screen.getByTestId("open-items");
    expect(panel.textContent).toContain("Open items(2)");
    const names = screen
      .getAllByRole("button", { name: /^Show item/ })
      .map((button) => button.getAttribute("aria-label"));
    // Header chips, then the expanded rows: recent, other open, closed.
    expect(names).toEqual([
      "Show item Q2 (closed), mentioned in the latest reply",
      "Show item Q3, mentioned in the latest reply",
      "Show item Q4",
      "Show item Q2 (closed), mentioned in the latest reply",
      "Show item Q3, mentioned in the latest reply",
      "Show item Q4",
      "Show item Q1 (closed)",
    ]);
    const chipClass = (name: string) => screen.getAllByRole("button", { name })[0].className;
    expect(chipClass("Show item Q3, mentioned in the latest reply")).toContain("bg-warning/15");
    expect(chipClass("Show item Q2 (closed), mentioned in the latest reply")).toContain(
      "line-through",
    );
    expect(chipClass("Show item Q4")).not.toContain("bg-warning/15");
    expect(panel.textContent).toMatch(/In the latest reply.*Other open \(1\).*Closed \(1\)/);
  });

  it("collapses on a press outside it, but not inside it or a popover", () => {
    renderPanel(
      indexOf("- **[Q1] Backfill window.** Batch it?\n- **[Q2] Soft-deleted rows.** Drop?"),
    );
    const panel = screen.getByTestId("open-items") as HTMLDetailsElement;
    const popover = document.createElement("div");
    popover.dataset.slot = "popover-content";
    document.body.append(popover);
    panel.open = true;

    fireEvent.pointerDown(panel.querySelector("summary")!);
    fireEvent.pointerDown(popover);
    expect(panel.open).toBe(true);
    fireEvent.pointerDown(document.body);
    expect(panel.open).toBe(false);
    popover.remove();
  });

  it("hides until the transcript uses labels", () => {
    renderPanel(indexOf("Use [A4] paper."));
    expect(screen.queryByTestId("open-items")).toBeNull();
  });

  it("shows as many header chips as fit the row, then +N", () => {
    const observers: ResizeObserverCallback[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: ResizeObserverCallback) {
          observers.push(callback);
        }
        observe() {}
        disconnect() {}
      },
    );
    // jsdom does no layout: chips measure 30px, the "+N" count 20px.
    let rowWidth = 100;
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(() => rowWidth);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      return { width: this.textContent?.startsWith("+") ? 20 : 30 } as DOMRect;
    });
    const labels = ["Q1", "Q2", "Q3", "Q4", "Q5"];
    renderPanel(indexOf(labels.map((label) => `- [${label}] Item.`).join("\n")));

    // Each item has a row in the expanded list, plus a header chip when shown.
    const headerChipCount = () => screen.getAllByRole("button", { name: /^Show item/ }).length - 5;
    expect(headerChipCount()).toBe(2);
    expect(screen.getByText("+3")).toBeTruthy();

    rowWidth = 200;
    act(() => observers.forEach((callback) => callback([], {} as ResizeObserver)));
    expect(headerChipCount()).toBe(5);
    expect(screen.queryByText("+3")).toBeNull();
  });
});

describe("fitItemChipCount", () => {
  it("fits chips and gaps, reserving room for +N only when some are left out", () => {
    // All three fit without a count: 30 + 4 + 30 + 4 + 30.
    expect(fitItemChipCount([30, 30, 30], 98, 4, 20)).toBe(3);
    // Two then the count: 30 + 4 + 30 + 4 + 20.
    expect(fitItemChipCount([30, 30, 30], 97, 4, 20)).toBe(2);
    expect(fitItemChipCount([30, 30, 30], 87, 4, 20)).toBe(1);
    expect(fitItemChipCount([60, 30], 50, 4, 20)).toBe(0);
    expect(fitItemChipCount([], 50, 4, 20)).toBe(0);
  });
});

describe("OpenItemsPanel dismissed items", () => {
  // The mutation observer notifies on a timer, so flush a macrotask.
  const flush = () =>
    act(
      () =>
        new Promise<void>((resolve) => {
          setTimeout(resolve, 0);
        }),
    );
  const twoOpen = () =>
    indexOf(
      "- **[Q1] Backfill window.** Batch it?\n- **[Q2] Soft-deleted rows.** Copy or drop?",
      "Looking.",
    );

  it("writes a dismissal to the session's labels and hides the item until restored", async () => {
    const labels = new Map<string, string>();
    let confirm: () => void = () => {};
    vi.mocked(updateSession).mockImplementation(async (id, updates) => {
      for (const [key, value] of Object.entries(updates.labels ?? {})) {
        if (value === null) labels.delete(key);
        else labels.set(key, value);
      }
      await new Promise<void>((resolve) => {
        confirm = resolve;
      });
      return { id, labels: Object.fromEntries(labels) } as Session;
    });
    renderPanel(twoOpen(), { id: "conv_1", labels: {} });
    const panel = screen.getByTestId("open-items");
    expect(panel.textContent).toContain("Open items(2)");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss item Q2" }));
    await flush();
    expect(updateSession).toHaveBeenCalledWith("conv_1", {
      labels: { [DISMISSED_ITEMS_LABEL_KEY]: "Q2" },
    });
    // Hidden while the write is still in flight.
    expect(screen.queryByRole("button", { name: "Show item Q2" })).toBeNull();
    expect(panel.textContent).toContain("Open items(1)");
    confirm();
    await flush();
    expect(screen.queryByRole("button", { name: "Show item Q2" })).toBeNull();
    expect(panel.textContent).toContain("Open items(1)");

    fireEvent.click(screen.getByRole("button", { name: "Show dismissed (1)" }));
    expect(screen.getByRole("button", { name: "Show item Q2" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restore item Q2" }));
    await flush();
    expect(updateSession).toHaveBeenLastCalledWith("conv_1", {
      labels: { [DISMISSED_ITEMS_LABEL_KEY]: null },
    });
    confirm();
    await flush();
    expect(labels.has(DISMISSED_ITEMS_LABEL_KEY)).toBe(false);
    expect(panel.textContent).toContain("Open items(2)");
    expect(screen.queryByRole("button", { name: /dismissed/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Show item Q2" })).toHaveLength(2);
  });

  it("starts from the dismissals stored on the session", () => {
    renderPanel(twoOpen(), { id: "conv_1", labels: { [DISMISSED_ITEMS_LABEL_KEY]: "Q1" } });
    expect(screen.getByTestId("open-items").textContent).toContain("Open items(1)");
    expect(screen.queryByRole("button", { name: "Show item Q1" })).toBeNull();
    expect(screen.getByRole("button", { name: "Show dismissed (1)" })).toBeTruthy();
  });

  it("shows a dismissed item again once the agent closes it", () => {
    renderPanel(indexOf("- **[Q1] Backfill window.**\n- **[Q2] Rows.**", "~~[Q1]~~ batched."), {
      id: "conv_1",
      labels: { [DISMISSED_ITEMS_LABEL_KEY]: "Q1" },
    });
    expect(
      screen.getAllByRole("button", {
        name: "Show item Q1 (closed), mentioned in the latest reply",
      }),
    ).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /dismissed/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss item Q1" })).toBeNull();
  });
});
