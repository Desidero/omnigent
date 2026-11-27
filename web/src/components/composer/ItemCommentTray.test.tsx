import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetItemCommentDraftsForTests, type ItemCommentDraft } from "@/lib/itemCommentDrafts";
import { buildItemLabelIndex } from "@/lib/itemLabels";
import { scanItemLabelSource } from "@/lib/itemComments";
import {
  ItemCommentModeHeader,
  ItemCommentTray,
  itemCommentSendLabel,
  itemCommentSendShortLabel,
  summarizeItemCommentDrafts,
} from "./ItemCommentTray";

function draft(id: string, label: string, text: string, files = 0): ItemCommentDraft {
  return {
    id,
    label,
    title: `${label} title`,
    text,
    files: Array.from({ length: files }, (_, at) => ({
      id: `${id}-f${at}`,
      name: `file-${at}.png`,
      type: "image/png",
      size: 1,
    })),
    createdAt: 1,
  };
}

const DRAFTS = [
  draft("d1", "Q2", "Use the account's zone.\nMore detail."),
  draft("d2", "Q2", "Store the zone per row.", 2),
  draft("d3", "R1", "Batch it."),
];

function renderTray(overrides: Partial<React.ComponentProps<typeof ItemCommentTray>> = {}) {
  const props = {
    drafts: DRAFTS,
    editingDraftId: null,
    onSend: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onDiscardAll: vi.fn(),
    ...overrides,
  };
  render(<ItemCommentTray {...props} />);
  return props;
}

afterEach(() => {
  cleanup();
  resetItemCommentDraftsForTests();
  localStorage.clear();
});

function expandTray() {
  fireEvent.click(screen.getByRole("button", { name: "Show comment drafts" }));
}

describe("ItemCommentTray", () => {
  it("lists each draft by label and first line, with edit and delete", () => {
    const props = renderTray();
    expandTray();
    const rows = screen.getAllByTestId("item-comment-draft-row");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Q2Use the account's zone.",
      "Q2Store the zone per row.2 attachments",
      "R1Batch it.",
    ]);
    expect(screen.getByText(/only on this browser/)).toBeTruthy();

    fireEvent.click(screen.getAllByRole("button", { name: "Edit draft on Q2" })[1]);
    expect(props.onEdit).toHaveBeenCalledWith("d2");
    fireEvent.click(screen.getByRole("button", { name: "Delete draft on R1" }));
    expect(props.onDelete).toHaveBeenCalledWith("d3");
  });

  it("starts collapsed, stays open until collapsed, and is collapsed again after a reload", () => {
    renderTray();
    expect(screen.queryAllByTestId("item-comment-draft-row")).toEqual([]);
    expect(screen.getByText("3 comments · Q2 ×2 · R1")).toBeTruthy();
    expandTray();
    expect(screen.getAllByTestId("item-comment-draft-row")).toHaveLength(3);
    expect(localStorage.length).toBe(0);
    cleanup();

    // Another composer in the same page keeps it open...
    renderTray();
    expect(screen.getAllByTestId("item-comment-draft-row")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Collapse comment drafts" }));
    expect(screen.queryAllByTestId("item-comment-draft-row")).toEqual([]);
    expandTray();
    cleanup();

    // ...and a reload starts collapsed.
    resetItemCommentDraftsForTests();
    renderTray();
    expect(screen.getByRole("button", { name: "Show comment drafts" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryAllByTestId("item-comment-draft-row")).toEqual([]);
  });

  it("sends every comment from one button, collapsed or not", () => {
    const props = renderTray();
    const send = screen.getByTestId("submit-item-comments");
    expect(send).toHaveAccessibleName("Send 3 comments");
    // Phones show the short label; each label truncates rather than overflowing.
    expect(within(send).getByText("Send 3")).toHaveClass("truncate", "sm:hidden");
    expect(within(send).getByText("Send 3 comments")).toHaveClass("truncate", "max-sm:hidden");
    expect(send).toHaveClass("min-w-0", "shrink");
    expect(send).not.toHaveAttribute("aria-describedby");
    fireEvent.click(send);
    expect(props.onSend).toHaveBeenCalledTimes(1);
    expandTray();
    expect(screen.getByRole("button", { name: "Send 3 comments" })).toBeTruthy();
  });

  it("names the typed message on the send button and describes where it goes", () => {
    renderTray({ drafts: [DRAFTS[2]], withMessage: true });
    const send = screen.getByRole("button", { name: "Send 1 comment + message" });
    expect(send).toHaveAccessibleDescription("The message you typed goes along as a General note.");
  });

  it("counts a new comment still being written and disables sending with a reason", () => {
    renderTray({ composingLabel: "R1", sendDisabledReason: "Waiting for agents…" });
    expect(screen.getByText("4 comments · Q2 ×2 · R1 ×2")).toBeTruthy();
    const send = screen.getByRole("button", { name: "Send 4 comments" });
    expect(send).toBeDisabled();
    expect(send).toHaveAttribute("title", "Waiting for agents…");
    expandTray();
    expect(screen.getByRole("list", { name: "Comment drafts" }).textContent).toContain(
      "R1Writing…",
    );
  });

  it("asks before discarding every draft", () => {
    const props = renderTray();
    expandTray();
    fireEvent.click(screen.getByRole("button", { name: "Discard all" }));
    expect(props.onDiscardAll).not.toHaveBeenCalled();
    expect(screen.queryByTestId("submit-item-comments")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Keep drafts" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard all" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm discard all drafts" }));
    expect(props.onDiscardAll).toHaveBeenCalledTimes(1);
  });

  it("marks the draft being edited and renders nothing without drafts", () => {
    renderTray({ editingDraftId: "d3" });
    expandTray();
    expect(screen.getByRole("button", { name: "Edit draft on R1" })).toBeDisabled();
    expect(screen.getByText("Editing…")).toBeTruthy();
    cleanup();

    renderTray({ drafts: [] });
    expect(screen.queryByTestId("item-comment-tray")).toBeNull();
  });

  it("summarizes drafts by item and labels the send button", () => {
    expect(summarizeItemCommentDrafts([DRAFTS[2]])).toBe("1 comment · R1");
    expect(itemCommentSendLabel(1, false)).toBe("Send 1 comment");
    expect(itemCommentSendLabel(3, true)).toBe("Send 3 comments + message");
    expect(itemCommentSendShortLabel(1, false)).toBe("Send 1");
    expect(itemCommentSendShortLabel(3, true)).toBe("Send 3 + message");
  });
});

describe("ItemCommentModeHeader", () => {
  const DEFINING_TEXT = [
    "Before I continue:",
    "",
    "1. **[R1] Backfill locking.** One transaction locks the table.",
    "2. **[Q2] Report cutoff timezone.** UTC or the account's zone?",
  ].join("\n");
  const ITEM = buildItemLabelIndex([
    scanItemLabelSource({ messageId: "a1", role: "assistant", text: DEFINING_TEXT }),
  ]).items.get("Q2");

  function renderHeader(item = ITEM ?? null) {
    const onLeave = vi.fn();
    render(
      <ItemCommentModeHeader
        label="Q2"
        title="Report cutoff timezone"
        item={item}
        excerpt="UTC or the account's zone?"
        editing={false}
        onLeave={onLeave}
      />,
    );
    return onLeave;
  }

  it("shows the item's full definition until collapsed to one line", () => {
    const onLeave = renderHeader();
    const definition = screen.getByRole("region", { name: "Q2 text" });
    expect(definition.textContent).toContain("Report cutoff timezone.");
    expect(definition.textContent).toContain("UTC or the account's zone?");
    expect(definition.textContent).not.toContain("Backfill locking");
    expect(definition.className).toContain("overflow-y-auto");
    expect(definition.className).toContain("max-h-");

    fireEvent.click(screen.getByRole("button", { name: "Collapse Q2 text" }));
    expect(screen.queryByRole("region", { name: "Q2 text" })).toBeNull();
    const header = screen.getByTestId("item-comment-mode");
    expect(within(header).getByText("UTC or the account's zone?")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Show Q2 text" }));
    expect(screen.getByRole("region", { name: "Q2 text" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Leave comment mode" }));
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("falls back to the one-line excerpt when the definition isn't loaded", () => {
    renderHeader(null);
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByRole("button", { name: /Q2 text/ })).toBeNull();
    expect(screen.getByText("UTC or the account's zone?")).toBeTruthy();
  });

  it("offers Comment and close only when asked to, and shows when it is on", () => {
    renderHeader();
    expect(screen.queryByRole("button", { name: "Comment and close" })).toBeNull();
    cleanup();
    const onClosesChange = vi.fn();
    const props = {
      label: "Q2",
      title: "Report cutoff timezone",
      item: ITEM ?? null,
      excerpt: "",
      editing: false,
      onLeave: vi.fn(),
      onClosesChange,
    };
    const { rerender } = render(<ItemCommentModeHeader {...props} closes={false} />);
    const toggle = screen.getByRole("button", { name: "Comment and close" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(toggle);
    expect(onClosesChange).toHaveBeenCalledWith(true);
    rerender(<ItemCommentModeHeader {...props} closes />);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("item-comment-mode").dataset.closes).toBe("true");
    fireEvent.click(toggle);
    expect(onClosesChange).toHaveBeenLastCalledWith(false);
  });
});

describe("ItemCommentTray with Comment and close", () => {
  const CLOSING = [{ ...DRAFTS[0], closes: true }, { ...DRAFTS[1], closes: true }, DRAFTS[2]];

  it("marks the items sending closes, collapsed and expanded, and toggles them per item", () => {
    const onToggleClose = vi.fn();
    renderTray({ drafts: CLOSING, closableLabels: new Set(["Q2", "R1"]), onToggleClose });
    expect(screen.getByRole("button", { name: "Show comment drafts" }).textContent).toContain(
      "3 comments · Q2 ×2 · R1 · closes Q2",
    );
    expandTray();
    const rows = screen.getAllByTestId("item-comment-draft-row");
    expect(rows.map((row) => within(row).queryByText("closes") !== null)).toEqual([
      true,
      true,
      false,
    ]);
    const r1Toggle = within(rows[2]).getByRole("button", { name: "Close R1 when sent" });
    expect(r1Toggle.getAttribute("aria-pressed")).toBe("false");
    expect(
      within(rows[0])
        .getByRole("button", { name: "Close Q2 when sent" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(r1Toggle);
    expect(onToggleClose).toHaveBeenCalledWith("R1");
  });

  it("shows no closing on items that cannot be closed", () => {
    renderTray({ drafts: CLOSING, onToggleClose: vi.fn() });
    expect(screen.getByRole("button", { name: "Show comment drafts" }).textContent).not.toContain(
      "closes",
    );
    expandTray();
    expect(screen.queryByText("closes")).toBeNull();
    expect(screen.queryByRole("button", { name: /when sent/ })).toBeNull();
  });

  it("marks a new comment being written that closes its item", () => {
    renderTray({
      drafts: [DRAFTS[2]],
      composingLabel: "Q2",
      composingCloses: true,
      closableLabels: new Set(["Q2"]),
    });
    expect(screen.getByRole("button", { name: "Show comment drafts" }).textContent).toContain(
      "2 comments · R1 · Q2 · closes Q2",
    );
  });
});
