// Search, filters and grouping for the Open items panel. They run in the
// browser over the session's loaded list (the store caps a session at 500
// items), so they need nothing from the server.

import { useSyncExternalStore } from "react";
import {
  OPEN_ITEM_KINDS,
  type OpenItemKind,
  type OpenItemRow,
  type OpenItemStatus,
} from "@/lib/openItems";
import { createStoredChoicePreference } from "@/lib/storedChoicePreference";

export type OpenItemGrouping = "status" | "topic" | "kind";
/** A kind chip: one of the store's kinds, or chat labels of other letters. */
export type OpenItemKindFilter = OpenItemKind | "other";

export interface OpenItemFilters {
  query: string;
  status: OpenItemStatus | null;
  kind: OpenItemKindFilter | null;
  topic: string | null;
}

export const NO_OPEN_ITEM_FILTERS: OpenItemFilters = {
  query: "",
  status: null,
  kind: null,
  topic: null,
};

export const OPEN_ITEM_STATUS_NAMES: Record<OpenItemStatus, string> = {
  open: "Open",
  answered: "Answered",
  closed: "Closed",
};

export function kindName(kind: OpenItemKindFilter): string {
  return OPEN_ITEM_KINDS.find((entry) => entry.kind === kind)?.name ?? "Other";
}

export function hasOpenItemFilters(filters: OpenItemFilters): boolean {
  return (
    filters.query.trim() !== "" ||
    filters.status !== null ||
    filters.kind !== null ||
    filters.topic !== null
  );
}

function rowKind(row: OpenItemRow): OpenItemKindFilter {
  return row.kind ?? "other";
}

/** Whether every word of `query` is in the row's label, title, detail or topic. */
export function rowMatchesQuery(row: OpenItemRow, query: string): boolean {
  const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = [row.label, row.title, row.detail, row.topic ?? ""].join("\n").toLocaleLowerCase();
  return words.every((word) => text.includes(word));
}

/** The rows the search and the selected chips keep. */
export function filterOpenItemRows(
  rows: readonly OpenItemRow[],
  filters: OpenItemFilters,
): OpenItemRow[] {
  return rows.filter(
    (row) =>
      rowMatchesQuery(row, filters.query) &&
      (filters.status === null || row.status === filters.status) &&
      (filters.kind === null || rowKind(row) === filters.kind) &&
      (filters.topic === null || row.topic === filters.topic),
  );
}

export interface OpenItemFacetCounts {
  status: Record<OpenItemStatus, number>;
  /** Kinds present, in label order. */
  kinds: { kind: OpenItemKindFilter; count: number }[];
  /** Topics present, by name. */
  topics: { topic: string; count: number }[];
}

/**
 * What each chip would show: per facet, the rows the search and the other
 * facets' chips keep, so a count is what selecting the chip lists.
 */
export function openItemFacetCounts(
  rows: readonly OpenItemRow[],
  filters: OpenItemFilters,
): OpenItemFacetCounts {
  const without = (facet: "status" | "kind" | "topic") =>
    filterOpenItemRows(rows, { ...filters, [facet]: null });
  const status: Record<OpenItemStatus, number> = { open: 0, answered: 0, closed: 0 };
  for (const row of without("status")) status[row.status] += 1;
  const kindCounts = new Map<OpenItemKindFilter, number>();
  for (const row of without("kind")) {
    kindCounts.set(rowKind(row), (kindCounts.get(rowKind(row)) ?? 0) + 1);
  }
  const topicCounts = new Map<string, number>();
  for (const row of without("topic")) {
    if (row.topic) topicCounts.set(row.topic, (topicCounts.get(row.topic) ?? 0) + 1);
  }
  const kindOrder: OpenItemKindFilter[] = [...OPEN_ITEM_KINDS.map(({ kind }) => kind), "other"];
  return {
    status,
    kinds: kindOrder.flatMap((kind) => {
      const count = kindCounts.get(kind);
      return count ? [{ kind, count }] : [];
    }),
    topics: [...topicCounts]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([topic, count]) => ({ topic, count })),
  };
}

export interface OpenItemGroup {
  key: string;
  title: string;
  rows: OpenItemRow[];
  /** Folded unless the user opens it: closed items, by default. */
  foldedByDefault: boolean;
}

const STATUS_ORDER: Record<OpenItemStatus, number> = { open: 0, answered: 1, closed: 2 };

function byStatus(rows: OpenItemRow[]): OpenItemRow[] {
  // Stable: rows keep label order within a status.
  return [...rows].sort((left, right) => STATUS_ORDER[left.status] - STATUS_ORDER[right.status]);
}

/**
 * Rows in groups. By status: what the latest reply mentions first, then
 * open, answered and closed (folded). By topic or kind: one group each, in
 * name or label order, open items first within a group.
 */
export function groupOpenItemRows(
  rows: readonly OpenItemRow[],
  grouping: OpenItemGrouping,
): OpenItemGroup[] {
  if (grouping === "status") {
    const recent = rows.filter((row) => row.recent);
    const rest = rows.filter((row) => !row.recent);
    const groups: OpenItemGroup[] = [
      { key: "recent", title: "In the latest reply", rows: recent, foldedByDefault: false },
    ];
    for (const status of ["open", "answered", "closed"] as const) {
      groups.push({
        key: status,
        title: OPEN_ITEM_STATUS_NAMES[status],
        rows: rest.filter((row) => row.status === status),
        foldedByDefault: status === "closed",
      });
    }
    return groups.filter((group) => group.rows.length > 0);
  }
  const keyOf = (row: OpenItemRow) => (grouping === "topic" ? (row.topic ?? "") : rowKind(row));
  const buckets = new Map<string, OpenItemRow[]>();
  for (const row of rows) {
    const key = keyOf(row);
    buckets.set(key, [...(buckets.get(key) ?? []), row]);
  }
  const keys =
    grouping === "topic"
      ? [...buckets.keys()].sort((left, right) =>
          // Items without a topic come last.
          left === "" ? 1 : right === "" ? -1 : left.localeCompare(right),
        )
      : [...OPEN_ITEM_KINDS.map(({ kind }) => kind as string), "other"].filter((key) =>
          buckets.has(key),
        );
  return keys.map((key) => ({
    key: `${grouping}:${key}`,
    title: grouping === "topic" ? key || "No topic" : kindName(key as OpenItemKindFilter),
    rows: byStatus(buckets.get(key) ?? []),
    foldedByDefault: false,
  }));
}

const groupingPreference = createStoredChoicePreference(
  "omnigent:open-items-grouping",
  ["status", "topic", "kind"],
  "status",
);

/** How this browser groups the Open items panel. */
export function useOpenItemGrouping(): OpenItemGrouping {
  return groupingPreference.use() as OpenItemGrouping;
}

export function writeOpenItemGrouping(grouping: OpenItemGrouping): void {
  groupingPreference.write(grouping);
}

/** The panel's search, chips and folds for one session. */
export interface OpenItemsView {
  filters: OpenItemFilters;
  /** Groups the user opened or folded, against their default. */
  toggledGroups: readonly string[];
}

const EMPTY_VIEW: OpenItemsView = { filters: NO_OPEN_ITEM_FILTERS, toggledGroups: [] };
// Kept for the page's lifetime, so the panel reopens as it was left.
const views = new Map<string, OpenItemsView>();
const viewListeners = new Set<() => void>();

function subscribeViews(listener: () => void): () => void {
  viewListeners.add(listener);
  return () => viewListeners.delete(listener);
}

export function readOpenItemsView(sessionId: string | null): OpenItemsView {
  return (sessionId && views.get(sessionId)) || EMPTY_VIEW;
}

export function writeOpenItemsView(sessionId: string | null, view: OpenItemsView): void {
  if (!sessionId) return;
  views.set(sessionId, view);
  for (const listener of viewListeners) listener();
}

/** The session's panel view, which outlives the panel closing until the page reloads. */
export function useOpenItemsView(
  sessionId: string | null,
): [OpenItemsView, (update: (view: OpenItemsView) => OpenItemsView) => void] {
  const view = useSyncExternalStore(subscribeViews, () => readOpenItemsView(sessionId));
  return [view, (update) => writeOpenItemsView(sessionId, update(readOpenItemsView(sessionId)))];
}
