// A session's stored open items (`/v1/sessions/{id}/open-items`), and the one
// index the chat and the panel read: a label the store holds takes its state
// from the store; a label only in the chat keeps the state the chat text gives
// it, shown as "chat only".

import type { QueryClient } from "@tanstack/react-query";
import { authenticatedFetch } from "@/lib/identity";
import {
  extractItemBlock,
  extractLabelSentence,
  itemLabelTitle,
  mentionedInLatestReply,
  type ItemLabelEntry,
  type ItemLabelIndex,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import { apiErrorFromResponse } from "@/lib/sessionsApi";
import { isLinkItemLabel, linksInMarkdown } from "@/lib/sessionLinks";

export type OpenItemKind = "question" | "risk" | "finding" | "follow_up" | "link";
export type OpenItemStatus = "open" | "answered" | "closed";

/** Kinds in label order, with the letter their labels start with. */
export const OPEN_ITEM_KINDS: readonly { kind: OpenItemKind; letter: string; name: string }[] = [
  { kind: "question", letter: "Q", name: "Questions" },
  { kind: "risk", letter: "R", name: "Risks" },
  { kind: "finding", letter: "F", name: "Findings" },
  { kind: "follow_up", letter: "T", name: "Follow-ups" },
  { kind: "link", letter: "L", name: "Links" },
];

export interface OpenItemLink {
  url: string;
  label?: string;
}

export interface OpenItemAnswer {
  text: string;
  /** Epoch seconds. */
  at: number;
  by: string | null;
}

/** One stored item, as `GET /v1/sessions/{id}/open-items` returns it. */
export interface StoredOpenItem {
  label: string;
  kind: OpenItemKind;
  number: number;
  status: OpenItemStatus;
  title: string;
  detail: string;
  topic: string | null;
  links: OpenItemLink[];
  url: string | null;
  raised_by: string | null;
  created_at: number;
  updated_at: number;
  closed_at: number | null;
  resolution: string | null;
  closed_by: "agent" | "user" | null;
  answers: OpenItemAnswer[];
}

interface OpenItemsPage {
  data: StoredOpenItem[];
  has_more: boolean;
  next_after: string | null;
}

/** A change a person makes to one item through `PATCH …/open-items`. */
export interface OpenItemUpdate {
  label: string;
  status?: "open" | "closed";
  /** Required to close. */
  resolution?: string;
  /** Empty clears it. */
  topic?: string;
}

/** Per-label outcome of a write: the item as stored now, or why it was refused. */
export type OpenItemWriteResult =
  | { label: string; item: StoredOpenItem }
  | { label: string; error: { code: string; message: string } };

// The store caps a session at 500 items; pages of 200 read them all in three requests.
const PAGE_LIMIT = "200";
// The store's limits on what an item carries.
const TITLE_MAX_CHARS = 160;
const DETAIL_MAX_CHARS = 6000;
const RESOLUTION_MAX_CHARS = 2000;
// Items per import request, as per raise.
const IMPORT_BATCH = 10;
const MAX_PAGES = 5;

export function openItemsKey(sessionId: string | undefined) {
  return ["session-open-items", sessionId] as const;
}

/** Refetch a session's stored items, e.g. after `session.open_items.changed`. */
export function refreshStoredOpenItems(queryClient: QueryClient, sessionId: string): void {
  void queryClient.invalidateQueries({ queryKey: openItemsKey(sessionId), exact: true });
}

function openItemsUrl(sessionId: string, suffix = ""): string {
  return `/v1/sessions/${encodeURIComponent(sessionId)}/open-items${suffix}`;
}

/** Every stored item of the session, in label order. */
export async function fetchStoredOpenItems(sessionId: string): Promise<StoredOpenItem[]> {
  const items: StoredOpenItem[] = [];
  let after: string | null = null;
  /* oxlint-disable no-await-in-loop -- each page starts after the previous page's last label */
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const params = new URLSearchParams({ status: "all", limit: PAGE_LIMIT });
    if (after) params.set("after", after);
    const response = await authenticatedFetch(`${openItemsUrl(sessionId)}?${params}`);
    if (!response.ok) throw await apiErrorFromResponse(response);
    const body = (await response.json()) as OpenItemsPage;
    items.push(...body.data);
    if (!body.has_more || !body.next_after) break;
    after = body.next_after;
  }
  /* oxlint-enable no-await-in-loop */
  return items;
}

/** Close, reopen or retopic items as the signed-in person (edit access). */
export async function updateStoredOpenItems(
  sessionId: string,
  updates: readonly OpenItemUpdate[],
): Promise<OpenItemWriteResult[]> {
  const response = await authenticatedFetch(openItemsUrl(sessionId), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates }),
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
  return ((await response.json()) as { items: OpenItemWriteResult[] }).items;
}

/** A chat item to store under its chat label; see `POST …/open-items/import`. */
export interface ChatItemImport {
  kind: OpenItemKind;
  label: string;
  title: string;
  detail: string;
  url?: string;
  /** Stores it closed, for an item the chat closed or the user dismissed. */
  resolution?: string;
}

/**
 * Store chat items under their own labels (edit access), ten per request.
 * Labels already stored come back with `label_taken` and are left as they are.
 */
export async function importChatItems(
  sessionId: string,
  items: readonly ChatItemImport[],
): Promise<OpenItemWriteResult[]> {
  const batchKey = `import:${crypto.randomUUID()}`;
  const results: OpenItemWriteResult[] = [];
  /* oxlint-disable no-await-in-loop -- later batches move the counters past earlier ones */
  for (let start = 0; start < items.length; start += IMPORT_BATCH) {
    const batch = items.slice(start, start + IMPORT_BATCH);
    const response = await authenticatedFetch(openItemsUrl(sessionId, "/import"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: batch, idempotency_key: `${batchKey}:${start}` }),
    });
    if (!response.ok) throw await apiErrorFromResponse(response);
    const body = (await response.json()) as {
      items: ({ item: StoredOpenItem } | { error: { code: string; message: string } })[];
    };
    body.items.forEach((row, position) => {
      const label = batch[position].label;
      results.push("item" in row ? { label, item: row.item } : { label, error: row.error });
    });
  }
  /* oxlint-enable no-await-in-loop */
  return results;
}

/** The cached list with the items a write returned put in place. */
export function withWrittenItems(
  items: readonly StoredOpenItem[] | undefined,
  results: readonly OpenItemWriteResult[],
): StoredOpenItem[] | undefined {
  if (!items) return undefined;
  const written = new Map(
    results.flatMap((result) => ("item" in result ? [[result.item.label, result.item]] : [])),
  );
  if (written.size === 0) return [...items];
  const kept = items.map((item) => written.get(item.label) ?? item);
  const known = new Set(items.map((item) => item.label));
  const added = [...written.values()].filter((item) => !known.has(item.label));
  return added.length === 0 ? kept : sortByLabel([...kept, ...added]);
}

const KIND_ORDER = new Map(OPEN_ITEM_KINDS.map(({ letter }, position) => [letter, position]));
const LABEL_PARTS_RE = /^([A-Z]{1,3})(\d{1,3})$/;

/** Label order, as the store lists: by kind, then number; other letters last. */
export function compareItemLabels(left: string, right: string): number {
  const [, leftLetter = left, leftNumber = "0"] = left.match(LABEL_PARTS_RE) ?? [];
  const [, rightLetter = right, rightNumber = "0"] = right.match(LABEL_PARTS_RE) ?? [];
  const leftKind = KIND_ORDER.get(leftLetter) ?? KIND_ORDER.size;
  const rightKind = KIND_ORDER.get(rightLetter) ?? KIND_ORDER.size;
  if (leftKind !== rightKind) return leftKind - rightKind;
  if (leftLetter !== rightLetter) return leftLetter < rightLetter ? -1 : 1;
  return Number(leftNumber) - Number(rightNumber);
}

function sortByLabel(items: StoredOpenItem[]): StoredOpenItem[] {
  return items.sort((left, right) => compareItemLabels(left.label, right.label));
}

/** The kind a chat label names, when it is a label the store could hold. */
export function kindOfLabel(label: string): OpenItemKind | null {
  const match = label.match(/^([QRFTL])[1-9]\d{0,2}$/);
  return match ? (OPEN_ITEM_KINDS.find(({ letter }) => letter === match[1])?.kind ?? null) : null;
}

/** What the store adds to a chat item: its stored record, and a close only the chat made. */
export interface StoredItemFields {
  stored?: StoredOpenItem;
  /** The chat struck the label while the store keeps the item open; offered as a one-tap close. */
  closedInChat?: ItemLabelSource;
}

export type MergedItemLabelEntry = ItemLabelEntry & StoredItemFields;

/** The stored record behind an index entry, if the store holds its label. */
export function storedItemOf(entry: ItemLabelEntry): StoredOpenItem | undefined {
  return (entry as MergedItemLabelEntry).stored;
}

/**
 * The transcript's label index with stored state applied: a stored item is
 * closed exactly when the store says so. A store close the chat never wrote
 * is described by its resolution, at the label's latest mention.
 *
 * @returns `index` itself without stored items, so a session the store knows
 *   nothing about renders as before.
 */
export function mergeStoredOpenItems(
  index: ItemLabelIndex,
  stored: readonly StoredOpenItem[] | null,
): ItemLabelIndex {
  if (!stored || stored.length === 0) return index;
  const byLabel = new Map(stored.map((item) => [item.label, item]));
  let storedInChat = false;
  const items = new Map<string, ItemLabelEntry>();
  for (const [label, entry] of index.items) {
    const item = byLabel.get(label);
    if (!item) {
      items.set(label, entry);
      continue;
    }
    storedInChat = true;
    const merged: MergedItemLabelEntry = { ...entry, stored: item };
    if (item.status === "closed") {
      merged.closedBy = entry.closedBy ?? storeClosingSource(entry, item);
    } else {
      merged.closedBy = null;
      if (entry.closedBy) merged.closedInChat = entry.closedBy;
    }
    items.set(label, merged);
  }
  return { ...index, enabled: index.enabled || storedInChat, items };
}

function storeClosingSource(entry: ItemLabelEntry, item: StoredOpenItem): ItemLabelSource {
  const resolution = item.resolution?.trim();
  return {
    messageId: entry.lastMention.messageId,
    role: item.closed_by === "user" ? "user" : "assistant",
    text: resolution ? `~~[${item.label}]~~ ${resolution}` : `~~[${item.label}]~~`,
    ...(item.closed_at !== null ? { createdAtS: item.closed_at } : {}),
  };
}

/** One row of the Open items panel: a stored item, or a label only the chat has. */
export interface OpenItemRow {
  label: string;
  /** Null for a chat label of a letter the store does not use, e.g. `[A4]`. */
  kind: OpenItemKind | null;
  status: OpenItemStatus;
  title: string;
  detail: string;
  topic: string | null;
  /** The stored record; null for a chat-only item. */
  stored: StoredOpenItem | null;
  /** Where the chat defines or mentions it; null when no loaded message does. */
  entry: MergedItemLabelEntry | null;
  /** The latest agent reply mentions it. */
  recent: boolean;
  /** Dismissed from the panel (chat-only items, stored on the session's labels). */
  dismissed: boolean;
}

/**
 * The panel's rows in label order: every stored item but pinned links, then
 * the chat's own labels the store does not hold. Chat labels count only once
 * the transcript uses labels, as the chips do.
 */
export function openItemRows(
  index: ItemLabelIndex | null,
  stored: readonly StoredOpenItem[],
  dismissed: ReadonlySet<string>,
): OpenItemRow[] {
  const rows: OpenItemRow[] = [];
  const storedLabels = new Set<string>();
  for (const item of stored) {
    storedLabels.add(item.label);
    if (item.kind === "link") continue;
    const entry = (index?.items.get(item.label) as MergedItemLabelEntry | undefined) ?? null;
    rows.push({
      label: item.label,
      kind: item.kind,
      status: item.status,
      title: item.title,
      detail: item.detail,
      topic: item.topic,
      stored: item,
      entry,
      recent: entry !== null && index !== null && mentionedInLatestReply(index, entry),
      dismissed: false,
    });
  }
  if (index?.enabled) {
    for (const entry of index.items.values()) {
      if (storedLabels.has(entry.label) || isLinkItemLabel(entry.label)) continue;
      const closed = entry.closedBy !== null;
      rows.push({
        label: entry.label,
        kind: kindOfLabel(entry.label),
        status: closed ? "closed" : "open",
        title: itemLabelTitle(entry.source.text, entry.label),
        detail: extractItemBlock(entry.source.text, entry.label) ?? "",
        topic: null,
        stored: null,
        entry,
        recent: mentionedInLatestReply(index, entry),
        dismissed: !closed && dismissed.has(entry.label),
      });
    }
  }
  return rows.sort((left, right) => compareItemLabels(left.label, right.label));
}

/** How many rows wait on the user: open, not dismissed. Answered items wait on the agent. */
export function countOpenRows(rows: readonly OpenItemRow[]): number {
  return rows.filter((row) => row.status === "open" && !row.dismissed).length;
}

/** What an import records for a chat item the user dismissed. */
export const DISMISSED_RESOLUTION = "Dismissed from the Open items panel";

/**
 * The chat's labels the store does not hold, as an import would store them:
 * items of the store's letters, and pinned links whose block has a URL.
 * Closed items keep the sentence that closed them; dismissed ones are closed.
 */
export function chatItemsToImport(
  index: ItemLabelIndex | null,
  stored: readonly StoredOpenItem[],
  dismissed: ReadonlySet<string>,
): ChatItemImport[] {
  if (!index?.enabled) return [];
  const storedLabels = new Set(stored.map((item) => item.label));
  const imports: ChatItemImport[] = [];
  for (const entry of index.items.values()) {
    const kind = kindOfLabel(entry.label);
    if (!kind || storedLabels.has(entry.label)) continue;
    const block = extractItemBlock(entry.source.text, entry.label) ?? "";
    const item: ChatItemImport = {
      kind,
      label: entry.label,
      title: (itemLabelTitle(entry.source.text, entry.label) || entry.label).slice(
        0,
        TITLE_MAX_CHARS,
      ),
      detail: block.slice(0, DETAIL_MAX_CHARS),
    };
    if (kind === "link") {
      const url = linksInMarkdown(block)[0]?.url.href;
      if (!url) continue;
      item.url = url;
    }
    if (entry.closedBy) {
      const sentence = extractLabelSentence(entry.closedBy.text, entry.label);
      item.resolution =
        sentence?.replace(/~~/g, "").trim().slice(0, RESOLUTION_MAX_CHARS) || "Closed in the chat";
    } else if (dismissed.has(entry.label)) {
      item.resolution = DISMISSED_RESOLUTION;
    }
    imports.push(item);
  }
  return imports;
}

/** The sentence that closed an item in chat, as a resolution for the store. */
export function chatResolution(row: OpenItemRow): string | null {
  const closing = row.entry?.closedInChat ?? (row.stored ? null : row.entry?.closedBy);
  if (!closing) return null;
  const sentence = extractLabelSentence(closing.text, row.label);
  return sentence ? sentence.replace(/~~/g, "").trim().slice(0, RESOLUTION_MAX_CHARS) : null;
}
