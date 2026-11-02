import { describe, expect, it } from "vitest";
import type { ExtensionCatalogItem, ExtensionSlotItem } from "@/extensions/types";
import {
  CORE_SESSION_ROW_DECORATIONS,
  CORE_SESSION_ROW_MENU,
  resolveSessionRowEntries,
  type SessionRowLabel,
} from "./sessionRowSlots";

function extensionItem(id: string, order: number): SessionRowLabel {
  const item: ExtensionSlotItem = {
    id,
    slot: "session.row.menu",
    kind: "set-label",
    label: id,
    page: null,
    icon: null,
    order,
    when: "never",
    binding: { source: "label", key: `ext.${id}` },
  };
  return {
    extension: {} as ExtensionCatalogItem,
    item,
    label: { key: `ext.${id}`, title: id, values: [] },
    value: null,
  };
}

describe("resolveSessionRowEntries", () => {
  it("lists core's visible entries first, then extension items by order and id", () => {
    const entries = resolveSessionRowEntries(
      CORE_SESSION_ROW_MENU,
      [extensionItem("b.menu", 500), extensionItem("a.menu", 500), extensionItem("c.menu", 10)],
      { isOwner: true, canMarkUnread: true },
    );

    expect(entries.map((entry) => entry.id)).toEqual([
      "core.session.mark-unread",
      "c.menu",
      "a.menu",
      "b.menu",
    ]);
  });

  it("evaluates core predicates only; an extension's when stays unevaluated", () => {
    const read = resolveSessionRowEntries(CORE_SESSION_ROW_MENU, [extensionItem("a.menu", 1)], {
      isOwner: false,
      canMarkUnread: false,
    });
    expect(read.map((entry) => entry.id)).toEqual(["core.session.mark-read", "a.menu"]);

    const owned = resolveSessionRowEntries(CORE_SESSION_ROW_DECORATIONS, [], {
      isOwner: true,
      canMarkUnread: true,
    });
    expect(owned).toEqual([]);
  });
});
