// Records the user's comments on stored open items as their answers, once the
// "Comments on N items" message that carries them has posted, so the items
// show as answered. Best effort: the message already reached the agent, so a
// failed record only leaves the items open.
//
// "Comment and close" marks an item's comments to close it as well: its
// heading says so to the agent, and after the post the item is closed by the
// user with the comment as its resolution. Offered only for stored items that
// are not closed, so never on a server without open items.

import { useMemo, useSyncExternalStore } from "react";
import { showToast } from "@/components/ui/toast";
import { getCachedServerInfo } from "@/lib/capabilities";
import { authenticatedFetch } from "@/lib/identity";
import {
  getItemCommentState,
  saveItemCommentDraft,
  useItemCommentState,
} from "@/lib/itemCommentDrafts";
import { parseItemCommentMessage } from "@/lib/itemComments";
import {
  kindOfLabel,
  updateStoredOpenItems,
  type OpenItemWriteResult,
  type StoredOpenItem,
} from "@/lib/openItems";
import { apiErrorFromResponse } from "@/lib/sessionsApi";

// The store's limits: one answer's (and resolution's) length, items per request.
const ANSWER_MAX_CHARS = 2000;
const ITEMS_PER_REQUEST = 20;

/** Ends the heading of an item the user closes with the comment, in the user's voice. */
export const CLOSED_BY_USER_MARK = "(closed by me)";

export interface OpenItemAnswerInput {
  label: string;
  text: string;
}

/** The heading title of an item's comments, marked when they close it. */
export function itemCommentHeadingTitle(title: string, closes: boolean): string {
  return closes ? `${title} ${CLOSED_BY_USER_MARK}`.trim() : title;
}

/**
 * The answers a comment message gives: per item section, its comments joined,
 * for labels the store could hold. Attachment-only comments name their files.
 */
export function answersInCommentMessage(text: string): OpenItemAnswerInput[] {
  const parsed = parseItemCommentMessage(text);
  if (!parsed) return [];
  return parsed.sections.flatMap((section) => {
    if (!kindOfLabel(section.label)) return [];
    const answer = section.comments
      .map(
        (comment) =>
          comment.text.trim() ||
          (comment.attachments.length > 0 ? `Attachments: ${comment.attachments.join(", ")}` : ""),
      )
      .filter(Boolean)
      .join("\n\n")
      .slice(0, ANSWER_MAX_CHARS);
    return answer ? [{ label: section.label, text: answer }] : [];
  });
}

/** `POST /v1/sessions/{id}/open-items/answers`; a label the store lacks is skipped there. */
export async function recordOpenItemAnswers(
  sessionId: string,
  answers: readonly OpenItemAnswerInput[],
): Promise<void> {
  /* oxlint-disable no-await-in-loop -- a few small requests, in order */
  for (let start = 0; start < answers.length; start += ITEMS_PER_REQUEST) {
    const response = await authenticatedFetch(
      `/v1/sessions/${encodeURIComponent(sessionId)}/open-items/answers`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: answers.slice(start, start + ITEMS_PER_REQUEST) }),
      },
    );
    if (!response.ok) throw await apiErrorFromResponse(response);
  }
  /* oxlint-enable no-await-in-loop */
}

/** Closes `answers`' items as the user, each with its answer as the resolution. */
async function closeAnsweredItems(
  sessionId: string,
  answers: readonly OpenItemAnswerInput[],
): Promise<string[]> {
  const refused: string[] = [];
  /* oxlint-disable no-await-in-loop -- a few small requests, in order */
  for (let start = 0; start < answers.length; start += ITEMS_PER_REQUEST) {
    const batch = answers.slice(start, start + ITEMS_PER_REQUEST);
    try {
      const results: OpenItemWriteResult[] = await updateStoredOpenItems(
        sessionId,
        batch.map(({ label, text }) => ({ label, status: "closed", resolution: text })),
      );
      refused.push(...results.flatMap((result) => ("error" in result ? [result.label] : [])));
    } catch (error) {
      console.warn("Couldn't close the open items", error);
      refused.push(...batch.map(({ label }) => label));
    }
  }
  /* oxlint-enable no-await-in-loop */
  return refused;
}

/**
 * After a comment message posted: record its comments on the stored items
 * they name, where the server stores open items, and close the items in
 * `closes` with them. Never throws; a close that fails leaves the item open
 * and says so in a toast.
 */
export async function recordItemCommentAnswers(
  sessionId: string,
  messageText: string,
  closes: readonly string[] = [],
): Promise<void> {
  if (getCachedServerInfo()?.open_items !== true) return;
  const answers = answersInCommentMessage(messageText);
  if (answers.length === 0) return;
  try {
    await recordOpenItemAnswers(sessionId, answers);
  } catch (error) {
    // The agent has the message; the items just stay open in the panel.
    console.warn("Couldn't record the comments as answers to the open items", error);
  }
  const closing = new Set(Array.isArray(closes) ? closes : []);
  const toClose = answers.filter(({ label }) => closing.has(label));
  if (toClose.length === 0) return;
  const refused = await closeAnsweredItems(sessionId, toClose);
  if (refused.length > 0) {
    const open = refused.length === 1 ? "it stays open" : "they stay open";
    showToast(`Your comments were sent, but ${refused.join(", ")} couldn't be closed; ${open}.`);
  }
}

// Stored items that can still be closed, per session, published by the
// stored-items query so the composer can offer "Comment and close" without it.
const closableBySession = new Map<string, ReadonlySet<string>>();
const closableListeners = new Set<() => void>();
const NONE: ReadonlySet<string> = new Set();

function subscribeClosable(listener: () => void): () => void {
  closableListeners.add(listener);
  return () => closableListeners.delete(listener);
}

/** Records a session's stored items as read; null where the store is unavailable. */
export function publishStoredOpenItems(
  sessionId: string,
  stored: readonly StoredOpenItem[] | null,
): void {
  const labels = (stored ?? []).filter((item) => item.status !== "closed").map((i) => i.label);
  const previous = closableBySession.get(sessionId) ?? NONE;
  if (previous.size === labels.length && labels.every((label) => previous.has(label))) return;
  if (labels.length === 0) closableBySession.delete(sessionId);
  else closableBySession.set(sessionId, new Set(labels));
  for (const listener of closableListeners) listener();
}

/** Labels of the session's stored items that are not closed. */
export function closableItemLabels(sessionId: string | null): ReadonlySet<string> {
  return (sessionId !== null && closableBySession.get(sessionId)) || NONE;
}

export function useClosableItemLabels(sessionId: string | null): ReadonlySet<string> {
  return useSyncExternalStore(
    subscribeClosable,
    () => closableItemLabels(sessionId),
    () => NONE,
  );
}

/** Sets whether the item's unsent comments close it. */
export function setItemCommentsClose(sessionId: string, label: string, closes: boolean): void {
  for (const draft of getItemCommentState(sessionId).drafts) {
    if (draft.label !== label || draft.submissionId || Boolean(draft.closes) === closes) continue;
    const next = { ...draft };
    if (closes) next.closes = true;
    else delete next.closes;
    saveItemCommentDraft(sessionId, next);
  }
}

/** Labels whose drafts close them when sent, submitted ones until they post. */
export function useItemCommentClosingLabels(sessionId: string | null): ReadonlySet<string> {
  const { drafts } = useItemCommentState(sessionId);
  return useMemo(
    () => new Set(drafts.filter((draft) => draft.closes).map((draft) => draft.label)),
    [drafts],
  );
}

/** Forgets every published item, for tests. */
export function resetClosableItemLabelsForTests(): void {
  closableBySession.clear();
  for (const listener of closableListeners) listener();
}
