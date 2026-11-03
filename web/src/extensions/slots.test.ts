import { describe, expect, it } from "vitest";
import {
  listedFieldValue,
  publishedFieldText,
  resolveCommandSlotItems,
  resolveFieldSlotItems,
  resolveSlotItems,
} from "./slots";
import type { ExtensionCatalogItem, ExtensionCommand, ExtensionSlotItem } from "./types";

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

const status = {
  key: "status",
  visibility: "published" as const,
  max_length: 16,
  values: [{ value: "done", label: "Done", icon: "circle-check", tone: "success" as const }],
};
const setStatus: ExtensionCommand = {
  id: "acme.review.set",
  title: "Set status",
  arguments: [{ name: "status", choices: ["done", "other"], pattern: null, max_length: 64 }],
  required_access: "edit",
  confirm: null,
  action: { type: "set_state", field: "status", value: "{status}" },
};

function rowItem(changes: Partial<ExtensionSlotItem>): ExtensionSlotItem {
  return {
    id: "acme.review.row",
    slot: "session.row.menu",
    kind: "command",
    label: "Status",
    page: null,
    icon: null,
    order: 500,
    when: null,
    ...changes,
  };
}

function withRows(
  slotItems: ExtensionSlotItem[],
  commands: ExtensionCommand[] = [setStatus],
): ExtensionCatalogItem {
  return { ...extension, slot_items: slotItems, state_fields: [status], commands };
}

describe("resolveFieldSlotItems", () => {
  it("binds only the same extension's published fields", () => {
    const badge = rowItem({
      slot: "session.row.decorations",
      kind: "decoration",
      binding: { source: "published_field", key: "status" },
    });
    const unknown = { ...badge, id: "acme.review.other", binding: { ...badge.binding!, key: "x" } };

    const resolved = resolveFieldSlotItems([withRows([badge, unknown])], "session.row.decorations");

    expect(resolved.map(({ item, field }) => [item.id, field.key])).toEqual([
      ["acme.review.row", "status"],
    ]);
  });
});

describe("resolveCommandSlotItems", () => {
  it("lists choices with the field's presentation when the command writes the bare argument", () => {
    const [entry] = resolveCommandSlotItems(
      [withRows([rowItem({ command: setStatus.id })])],
      "session.row.menu",
    );

    expect(entry.field?.key).toBe("status");
    expect(entry.choices).toEqual([
      { argument: "done", presentation: status.values[0] },
      { argument: "other", presentation: null },
    ]);
  });

  it("shows plain choices when the value is not the bare argument", () => {
    const templated = {
      ...setStatus,
      action: { ...setStatus.action, value: "x-{status}" },
    };
    const [entry] = resolveCommandSlotItems(
      [withRows([rowItem({ command: setStatus.id })], [templated])],
      "session.row.menu",
    );

    expect(entry.field).toBeNull();
    expect(entry.choices?.map((choice) => choice.presentation)).toEqual([null, null]);
  });

  it("drops items whose command is missing or takes a free-form argument", () => {
    const free = {
      ...setStatus,
      arguments: [{ name: "status", choices: [], pattern: "[a-z]+", max_length: 8 }],
    };
    expect(
      resolveCommandSlotItems(
        [withRows([rowItem({ command: "acme.review.gone" })])],
        "session.row.menu",
      ),
    ).toEqual([]);
    expect(
      resolveCommandSlotItems(
        [withRows([rowItem({ command: setStatus.id })], [free])],
        "session.row.menu",
      ),
    ).toEqual([]);
  });
});

describe("published field values", () => {
  it("reads own keys only and treats empty as absent", () => {
    const fields = { "acme.review": { status: "done", empty: "" } };
    expect(publishedFieldText(fields, "acme.review", "status")).toBe("done");
    expect(publishedFieldText(fields, "acme.review", "empty")).toBeNull();
    expect(publishedFieldText(fields, "acme.review", "constructor")).toBeNull();
    expect(publishedFieldText(fields, "constructor", "status")).toBeNull();
    expect(publishedFieldText(undefined, "acme.review", "status")).toBeNull();
    expect(listedFieldValue(status, "done")).toEqual(status.values[0]);
    expect(listedFieldValue(status, "toString")).toBeNull();
  });
});
