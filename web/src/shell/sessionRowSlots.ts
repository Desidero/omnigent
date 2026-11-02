// Core and extension entries in the session-row slots: row decorations, the
// row menu and the row tooltip. Core entries render without the catalog.

import { useMemo } from "react";
import { MailIcon, MailOpenIcon, UsersIcon, type LucideIcon } from "lucide-react";
import { useExtensions } from "@/extensions/ExtensionProvider";
import {
  declaredLabelValue,
  resolveLabelSlotItems,
  type ResolvedLabelSlotItem,
} from "@/extensions/slots";
import type { ExtensionLabelTone, ExtensionLabelValue, ExtensionSlotId } from "@/extensions/types";

export interface SessionRowContext {
  isOwner: boolean;
  /** Whether the row offers "Mark as unread" (it isn't showing the unread dot). */
  canMarkUnread: boolean;
}

export interface CoreSessionRowEntry {
  id: `core.${string}`;
  label: string;
  /** Hover text, when it differs from the accessible label. */
  title?: string;
  icon: LucideIcon;
  testId: string;
  /** Position among core's entries; extension items always follow them. */
  order: number;
  /** Core-only and web-evaluated; extension items never carry one. */
  isVisible?: (context: SessionRowContext) => boolean;
}

export const CORE_SESSION_ROW_DECORATIONS: readonly CoreSessionRowEntry[] = [
  {
    id: "core.session.shared",
    label: "Shared session",
    title: "Shared with you",
    icon: UsersIcon,
    testId: "session-row-shared",
    order: 100,
    isVisible: (context) => !context.isOwner,
  },
];

export interface CoreSessionRowMenuEntry extends CoreSessionRowEntry {
  action: "markUnread" | "markRead";
}

// A conditional pair: every row offers exactly one read-state action.
export const CORE_SESSION_ROW_MENU: readonly CoreSessionRowMenuEntry[] = [
  {
    id: "core.session.mark-unread",
    label: "Mark as unread",
    icon: MailIcon,
    testId: "mark-unread-conversation",
    action: "markUnread",
    order: 100,
    isVisible: (context) => context.canMarkUnread,
  },
  {
    id: "core.session.mark-read",
    label: "Mark as read",
    icon: MailOpenIcon,
    testId: "mark-read-conversation",
    action: "markRead",
    order: 110,
    isVisible: (context) => !context.canMarkUnread,
  },
];

/** Most extension items one row shows per slot, across all extensions. */
export const MAX_EXTENSION_ROW_ITEMS = 2;

// Important, so menu items' muted icon colour doesn't override the tone.
const LABEL_TONE_CLASSES: Record<ExtensionLabelTone, string> = {
  neutral: "text-status-gray!",
  info: "text-status-blue!",
  success: "text-status-green!",
  warning: "text-status-yellow!",
  danger: "text-status-red!",
};

export function labelToneClass(tone: string): string {
  return Object.hasOwn(LABEL_TONE_CLASSES, tone)
    ? LABEL_TONE_CLASSES[tone as ExtensionLabelTone]
    : LABEL_TONE_CLASSES.neutral;
}

export interface SessionRowLabel extends ResolvedLabelSlotItem {
  /** The row's current declared value; null when absent, empty or unknown. */
  value: ExtensionLabelValue | null;
}

/** Extension items in one session-row slot, with the row's current values. */
export function useSessionRowLabels(
  slot: ExtensionSlotId,
  labels: Record<string, string> | null | undefined,
): SessionRowLabel[] {
  const extensions = useExtensions();
  const items = useMemo(
    () => resolveLabelSlotItems(extensions, slot).slice(0, MAX_EXTENSION_ROW_ITEMS),
    [extensions, slot],
  );
  return useMemo(
    () => items.map((entry) => ({ ...entry, value: declaredLabelValue(entry.label, labels) })),
    [items, labels],
  );
}

export type SessionRowEntry<Core extends CoreSessionRowEntry> =
  | { source: "core"; id: string; entry: Core }
  | { source: "extension"; id: string; entry: SessionRowLabel };

function byOrder(left: { order: number; id: string }, right: { order: number; id: string }) {
  return left.order - right.order || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
}

/**
 * One session-row slot's entries: core's visible entries, then extension
 * items, each by (order, id). Only core entries carry a visibility check;
 * an extension item shows whenever its slot does.
 */
export function resolveSessionRowEntries<Core extends CoreSessionRowEntry>(
  core: readonly Core[],
  extension: readonly SessionRowLabel[],
  context: SessionRowContext,
): SessionRowEntry<Core>[] {
  return [
    ...core
      .filter((entry) => entry.isVisible?.(context) ?? true)
      .sort(byOrder)
      .map((entry) => ({ source: "core" as const, id: entry.id, entry })),
    ...[...extension]
      .sort((left, right) =>
        byOrder(
          { order: left.item.order, id: left.item.id },
          { order: right.item.order, id: right.item.id },
        ),
      )
      .map((entry) => ({ source: "extension" as const, id: entry.item.id, entry })),
  ];
}

/**
 * A slot's resolved entries for one row. `showExtension` is the surface's own
 * rule for extension items (a value to show, or edit access), not a predicate
 * the extension supplies.
 */
export function useSessionRowEntries<Core extends CoreSessionRowEntry>(
  slot: ExtensionSlotId,
  core: readonly Core[],
  labels: Record<string, string> | null | undefined,
  context: SessionRowContext,
  showExtension: (entry: SessionRowLabel) => boolean,
): SessionRowEntry<Core>[] {
  const extension = useSessionRowLabels(slot, labels);
  return resolveSessionRowEntries(core, extension.filter(showExtension), context);
}
