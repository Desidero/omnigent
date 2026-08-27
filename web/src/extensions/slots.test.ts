import { describe, expect, it } from "vitest";
import { resolveSlotItems } from "./slots";
import type { ExtensionCatalogItem } from "./types";

const extension: ExtensionCatalogItem = {
  object: "extension",
  id: "acme.review",
  display_name: "Review",
  distribution: "acme-review",
  version: "1.0.0",
  extension_api: 1,
  status: "enabled",
  permissions: [],
  pages: [
    { id: "acme.review.one", title: "One", route: "one", view: "one" },
    { id: "acme.review.two", title: "Two", route: "two", view: "two" },
  ],
  primary_navigation: [],
  slot_items: [
    {
      id: "acme.review.second",
      slot: "composer.actions",
      kind: "action",
      label: "Second",
      page: "acme.review.two",
      icon: null,
      order: 500,
      when: null,
    },
    {
      id: "acme.review.first",
      slot: "composer.actions",
      kind: "action",
      label: "First",
      page: "acme.review.one",
      icon: "search",
      order: 100,
      when: null,
    },
  ],
  browser: {
    declared: true,
    has_styles: false,
    digest: "digest",
    script_url: "/script",
    style_url: null,
  },
};

describe("resolveSlotItems", () => {
  it("selects one semantic slot and sorts by order then id", () => {
    expect(resolveSlotItems([extension], "composer.actions").map(({ item }) => item.id)).toEqual([
      "acme.review.first",
      "acme.review.second",
    ]);
    expect(resolveSlotItems([extension], "chat.header.actions")).toEqual([]);
  });

  it("drops a catalog item whose page reference is unavailable", () => {
    const broken = {
      ...extension,
      slot_items: [{ ...extension.slot_items[0], page: "acme.review.missing" }],
    };
    expect(resolveSlotItems([broken], "composer.actions")).toEqual([]);
  });
});
